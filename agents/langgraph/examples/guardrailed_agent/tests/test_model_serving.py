"""Classifier deployment contracts and recovery from incomplete setup."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

AGENT_DIR = Path(__file__).resolve().parents[1]
MODEL_SERVING_DIR = AGENT_DIR / "deploy" / "model-serving"


def _render_deployment(overlay: str) -> dict:
    cli = shutil.which("oc") or shutil.which("kubectl")
    if cli is None:
        pytest.skip("Install oc or kubectl to test rendered model-serving manifests")
    result = subprocess.run(
        [cli, "kustomize", str(MODEL_SERVING_DIR / overlay)],
        capture_output=True,
        text=True,
        check=True,
    )
    return next(
        doc for doc in yaml.safe_load_all(result.stdout) if doc["kind"] == "Deployment"
    )


@pytest.mark.parametrize("overlay", ["base", "overlays/t4"])
def test_model_serving_contract(overlay: str) -> None:
    """Both variants preserve the proxy's model name and can replace a busy GPU."""
    deployment = _render_deployment(overlay)
    args = deployment["spec"]["template"]["spec"]["containers"][0]["args"]
    cluster_env = (
        AGENT_DIR / "deploy" / "overlays" / "ci-testing" / "cluster.env.example"
    ).read_text()
    values = dict(
        line.split("=", 1)
        for line in cluster_env.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    served = args[args.index("--served-model-name") + 1]
    assert served == values["TOPIC_CONTROL_MODEL_ID"]
    assert "nemotron-3.5-content-safety" in served
    assert values["TOPIC_CONTROL_MODEL_ENGINE"] == "openai"
    assert values["TOPIC_CONTROL_LLM_BASE_URL"] == (
        "http://nemotron-3-5-content-safety-svc.llama-serving.svc.cluster.local:8080/v1"
    )
    assert deployment["spec"]["strategy"]["type"] == "Recreate"


def test_model_serving_t4_settings() -> None:
    """Check actual patch targeting and values through Kustomize."""
    deployment = _render_deployment("overlays/t4")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    args = container["args"]
    assert args[args.index("--dtype") + 1] == "half"
    assert args[args.index("--gpu-memory-utilization") + 1] == "0.70"
    assert json.loads(args[args.index("--hf-overrides") + 1]) == {
        "model_type": "nemotron35-content-safety"
    }
    env = {item["name"]: item["value"] for item in container["env"]}
    assert env["VLLM_USE_FLASHINFER_SAMPLER"] == "0"
    assert env["VLLM_ATTENTION_BACKEND"] == "TRITON_ATTN"


@pytest.fixture
def model_deploy_cli(tmp_path, monkeypatch):
    """Record deployment commands and emulate fresh ServiceAccount creation."""
    oc = tmp_path / "oc"
    oc.write_text(
        f"#!{sys.executable}\n"
        + textwrap.dedent("""\
            import json
            import os
            import sys
            from pathlib import Path

            root = Path(__file__).parent
            args = sys.argv[1:]
            with (root / "calls.jsonl").open("a") as log:
                log.write(json.dumps(args) + "\\n")
            if args[:2] == ["apply", "-f"]:
                if os.environ.get("FAIL_SERVICEACCOUNT"):
                    sys.exit(1)
                (root / "serviceaccount").touch()
            if "link" in args:
                if not (root / "serviceaccount").exists():
                    sys.exit(1)
                if os.environ.get("MISSING_PULL_SECRET"):
                    sys.exit(1)
                (root / "linked").touch()
            """)
    )
    oc.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return tmp_path


def _deploy_model(target: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "make",
            target,
            "AGENT_NAME=review",
            "CONTAINER_CLI=unused",
            "REPO_ROOT=unused",
            "GUARDRAILS_NAMESPACE=review",
            "MODEL_SERVING_NAMESPACE=review",
        ],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("target", "overlay"),
    [("deploy-model", "base"), ("deploy-model-t4", "overlays/t4")],
)
def test_fresh_deployment_links_credentials_before_workload(
    model_deploy_cli, target: str, overlay: str
) -> None:
    result = _deploy_model(target)
    assert result.returncode == 0, result.stderr
    assert (model_deploy_cli / "linked").exists()
    calls = [
        json.loads(line)
        for line in (model_deploy_cli / "calls.jsonl").read_text().splitlines()
    ]
    assert calls[0] == [
        "apply",
        "-f",
        "deploy/model-serving/base/serviceaccount.yaml",
        "-n",
        "review",
    ]
    assert calls[-2] == [
        "-n",
        "review",
        "secrets",
        "link",
        "nemotron-vllm",
        "dockerhub",
        "--for=pull",
    ]
    assert calls[-1] == [
        "apply",
        "-k",
        f"deploy/model-serving/{overlay}",
        "-n",
        "review",
    ]


def test_missing_optional_pull_secret_still_deploys(model_deploy_cli, monkeypatch):
    monkeypatch.setenv("MISSING_PULL_SECRET", "1")
    result = _deploy_model("deploy-model")
    assert result.returncode == 0, result.stderr
    assert "not linked" in result.stdout
    calls = (model_deploy_cli / "calls.jsonl").read_text().splitlines()
    assert json.loads(calls[-1])[:2] == ["apply", "-k"]


def test_serviceaccount_failure_stops_deployment(model_deploy_cli, monkeypatch):
    monkeypatch.setenv("FAIL_SERVICEACCOUNT", "1")
    result = _deploy_model("deploy-model")
    assert result.returncode != 0
    calls = (model_deploy_cli / "calls.jsonl").read_text().splitlines()
    assert len(calls) == 1


def test_interrupted_model_download_resumes_before_marking_complete(
    tmp_path, monkeypatch
):
    """A config file from a failed attempt must not bypass the next download."""
    deployment = next(
        doc
        for doc in yaml.safe_load_all(
            (MODEL_SERVING_DIR / "base" / "nemotron-vllm.yaml").read_text()
        )
        if doc["kind"] == "Deployment"
    )
    script = deployment["spec"]["template"]["spec"]["initContainers"][0]["args"][0]
    models = tmp_path / "models"
    models.mkdir()
    script = script.replace("/mnt/models", str(models))
    (tmp_path / "huggingface_hub.py").write_text(
        textwrap.dedent("""\
        from pathlib import Path

        def snapshot_download(*, local_dir, **kwargs):
            root = Path(local_dir)
            retry = (root / 'config.json').exists()
            (root / 'config.json').write_text('{}')
            if not retry:
                raise RuntimeError('interrupted after config download')
            (root / 'model.safetensors').touch()
        """)
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pip = bin_dir / "pip"
    pip.write_text("#!/bin/sh\nexit 0\n")
    pip.chmod(0o755)
    (bin_dir / "python").symlink_to(sys.executable)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))

    def run_download():
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    first = run_download()
    assert first.returncode != 0
    assert (models / "config.json").exists()
    assert not (models / ".download-complete").exists()
    second = run_download()
    assert second.returncode == 0, second.stderr
    assert (models / "model.safetensors").exists()
    assert (models / ".download-complete").exists()
    (tmp_path / "huggingface_hub.py").write_text("raise RuntimeError('must skip')\n")
    third = run_download()
    assert third.returncode == 0, third.stderr
    assert "skipping" in third.stdout
