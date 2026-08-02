"""Structural tests for RHOAI guardrails deploy manifests and scripts."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

AGENT_DIR = Path(__file__).resolve().parents[1]
DEPLOY_DIR = AGENT_DIR / "deploy"
MAKEFILE = (AGENT_DIR / "Makefile").read_text(encoding="utf-8")
RENDER_SCRIPT = DEPLOY_DIR / "scripts" / "render_guardrails_configmap.py"
CLUSTER_ENV_EXAMPLE = DEPLOY_DIR / "overlays" / "ci-testing" / "cluster.env.example"
CR_MANIFEST = DEPLOY_DIR / "manifests" / "03-nemoguardrails-cr.yaml"


def test_deploy_directory_layout() -> None:
    assert (DEPLOY_DIR / "README.md").is_file()
    assert (DEPLOY_DIR / "manifests" / "kustomization.yaml").is_file()
    assert (DEPLOY_DIR / "overlays" / "ci-testing" / "kustomization.yaml").is_file()
    assert RENDER_SCRIPT.is_file()


def test_cluster_env_example_points_at_vllm() -> None:
    text = CLUSTER_ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "vllm-svc.llama-serving.svc.cluster.local:8000" in text
    assert "qwen2-5-7b-instruct" in text
    assert "nemotron" in text
    assert "NVIDIA_API_KEY" in text


def test_nemoguardrails_cr_uses_nemoguard_config_id() -> None:
    doc = yaml.safe_load(CR_MANIFEST.read_text(encoding="utf-8"))
    configs = doc["spec"]["nemoConfigs"]
    assert configs[0]["name"] == "nemoguard"
    assert configs[0]["default"] is True
    assert "langgraph-guardrailed-agent-guardrails-config" in configs[0]["configMaps"]
    assert (
        doc["metadata"]["annotations"]["security.opendatahub.io/enable-auth"] == "false"
    )


def test_makefile_exposes_rhoai_deploy_targets() -> None:
    for target in (
        "render-guardrails-configmap",
        "deploy-guardrails-secrets",
        "deploy-guardrails",
        "undeploy-guardrails",
        "deploy-rhoai",
        "undeploy-rhoai",
        "deploy-rhoai-dry-run",
    ):
        assert re.search(rf"(?m)^{target}:", MAKEFILE)


def test_render_guardrails_configmap_produces_required_keys(tmp_path) -> None:
    output = tmp_path / "configmap.yaml"
    result = subprocess.run(
        [
            "python3",
            str(RENDER_SCRIPT),
            "--cluster-env",
            str(CLUSTER_ENV_EXAMPLE),
            "--output",
            str(output),
        ],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    doc = yaml.safe_load(output.read_text(encoding="utf-8"))
    keys = set(doc["data"].keys())
    assert keys == {
        "config.yaml",
        "prompts.yml",
        "rails.co",
        "actions.py",
        "topic_policy.co",
    }
    config = yaml.safe_load(doc["data"]["config.yaml"])
    assert config["passthrough"] is True
    flows = config["rails"]["input"]["flows"]
    assert "topic policy check input $model=topic_control" in flows
    topic = next(m for m in config["models"] if m["type"] == "topic_control")
    assert topic["engine"] == "nim"
    assert "nemotron-3.5-content-safety" in topic["model"]
