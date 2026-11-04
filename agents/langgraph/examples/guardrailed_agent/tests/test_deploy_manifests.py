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
    assert (DEPLOY_DIR / "overlays" / "ci-testing" / "cluster.env.example").is_file()
    assert not (DEPLOY_DIR / "manifests" / "kustomization.yaml").is_file()
    assert not (DEPLOY_DIR / "overlays" / "ci-testing" / "kustomization.yaml").is_file()
    assert RENDER_SCRIPT.is_file()
    assert (DEPLOY_DIR / "scripts" / "annotate_guardrails_route.py").is_file()


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


def _cluster_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in CLUSTER_ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def _model_serving_deployment() -> dict:
    docs = yaml.safe_load_all(
        (DEPLOY_DIR / "model-serving" / "base" / "nemotron-vllm.yaml").read_text(
            encoding="utf-8"
        )
    )
    return next(d for d in docs if d and d["kind"] == "Deployment")


def _model_serving_args() -> list:
    return _model_serving_deployment()["spec"]["template"]["spec"]["containers"][0][
        "args"
    ]


def test_cluster_env_example_topic_control_self_hosted() -> None:
    """Topic control points at the in-cluster vLLM, not the removed NIM."""
    values = _cluster_env_values()
    assert values["TOPIC_CONTROL_MODEL_ENGINE"] == "openai"
    assert values["TOPIC_CONTROL_LLM_BASE_URL"].startswith(
        "http://nemotron-3-5-content-safety-svc."
    )
    assert values["TOPIC_CONTROL_LLM_BASE_URL"].endswith(":8080/v1")


def test_model_serving_layout() -> None:
    assert (DEPLOY_DIR / "model-serving" / "base" / "kustomization.yaml").is_file()
    assert (DEPLOY_DIR / "model-serving" / "base" / "nemotron-vllm.yaml").is_file()
    assert (
        DEPLOY_DIR / "model-serving" / "overlays" / "t4" / "kustomization.yaml"
    ).is_file()


def test_model_serving_served_name_matches_topic_control_model_id() -> None:
    """vLLM 404s unknown model names; the guardrails proxy always sends
    TOPIC_CONTROL_MODEL_ID, so --served-model-name must equal it exactly."""
    args = _model_serving_args()
    served = args[args.index("--served-model-name") + 1]
    assert served == _cluster_env_values()["TOPIC_CONTROL_MODEL_ID"]


def test_model_serving_t4_overlay_keeps_served_name_and_flips_dtype() -> None:
    """Hermetic simulation of the T4 JSON patches: the overlay must only flip
    dtype/util and add env + --hf-overrides, never touch the served name."""
    args = list(_model_serving_args())
    overlay = yaml.safe_load(
        (
            DEPLOY_DIR / "model-serving" / "overlays" / "t4" / "kustomization.yaml"
        ).read_text(encoding="utf-8")
    )
    ops_text = ""
    for patch in overlay["patches"]:
        ops = yaml.safe_load(patch["patch"])
        ops_text += str(ops)
        for op in ops:
            path = op["path"]
            if op["op"] == "replace" and path.startswith(
                "/spec/template/spec/containers/0/args/"
            ):
                args[int(path.rsplit("/", 1)[1])] = op["value"]
            elif (
                op["op"] == "add" and path == "/spec/template/spec/containers/0/args/-"
            ):
                args.append(op["value"])
            else:
                assert path == "/spec/template/spec/containers/0/env", op
    served = args[args.index("--served-model-name") + 1]
    assert served == _cluster_env_values()["TOPIC_CONTROL_MODEL_ID"]
    assert args[args.index("--dtype") + 1] == "half"
    assert args[args.index("--hf-overrides") + 1] == (
        '{"model_type":"nemotron35-content-safety"}'
    )
    for env_name in ("VLLM_USE_FLASHINFER_SAMPLER", "VLLM_ATTENTION_BACKEND"):
        assert env_name in ops_text
    assert "TRITON_ATTN" in ops_text


def test_makefile_exposes_model_serving_targets() -> None:
    for target in ("deploy-model", "deploy-model-t4", "undeploy-model"):
        assert re.search(rf"(?m)^{target}:", MAKEFILE)
    assert "oc apply -k $(MODEL_SERVING_DIR)/base" in MAKEFILE
    assert "oc apply -k $(MODEL_SERVING_DIR)/overlays/t4" in MAKEFILE
    assert "MODEL_SERVING_NAMESPACE ?= llama-serving" in MAKEFILE


def test_render_guardrails_configmap_produces_required_keys(
    tmp_path, monkeypatch
) -> None:
    # Importing main.py (e.g. from test_api_contract) runs load_dotenv(), so a
    # developer's local .env with GUARDRAILS_TRACING_ENABLED=true can leak into
    # this subprocess and flip tracing on in the rendered config. Scrub it so
    # the tracing-off assertions below are hermetic (same guard as the
    # finalize_cr tests).
    monkeypatch.delenv("GUARDRAILS_TRACING_ENABLED", raising=False)
    sentinel_key = "nvapi-test-sentinel"
    openai_sentinel = "sk-test-sentinel"
    cluster_env = tmp_path / "cluster.env"
    cluster_env.write_text(
        CLUSTER_ENV_EXAMPLE.read_text(encoding="utf-8")
        .replace("NVIDIA_API_KEY=replace-me", f"NVIDIA_API_KEY={sentinel_key}")
        .replace("API_KEY=not-needed", f"API_KEY={openai_sentinel}"),
        encoding="utf-8",
    )
    output = tmp_path / "configmap.yaml"
    result = subprocess.run(
        [
            "python3",
            str(RENDER_SCRIPT),
            "--cluster-env",
            str(cluster_env),
            "--output",
            str(output),
        ],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    manifest_text = output.read_text(encoding="utf-8")
    assert sentinel_key not in manifest_text
    assert openai_sentinel not in manifest_text
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
    assert config["tracing"]["enabled"] is False
    assert config["tracing"]["enable_content_capture"] is False
    flows = config["rails"]["input"]["flows"]
    assert "topic policy check input $model=topic_control" in flows
    topic = next(m for m in config["models"] if m["type"] == "topic_control")
    # Self-hosted on in-cluster vLLM (RHAIENG-8048): NVIDIA removed the hosted
    # NIM function for this model, so the classifier runs beside the main LLM.
    assert topic["engine"] == "openai"
    assert "nemotron-3.5-content-safety" in topic["model"]
    assert "api_key" not in topic["parameters"]
    assert topic["api_key_env_var"] == "OPENAI_API_KEY"
    assert (
        "nemotron-3-5-content-safety-svc.llama-serving.svc.cluster.local:8080/v1"
        in topic["parameters"]["base_url"]
    )
    # Custom-policy mode keys off a substring of the model id — the id and the
    # vLLM --served-model-name must stay in lockstep (see
    # tests/test_deploy_manifests.py::test_model_serving_served_name_matches).
    assert "custom_policy" in topic["parameters"]["chat_template_kwargs"]
    assert topic["parameters"]["chat_template_kwargs"]["enable_thinking"] is False
    content = next(m for m in config["models"] if m["type"] == "content_safety")
    assert content["engine"] == "nim"
    assert "api_key" not in content["parameters"]
    assert content["api_key_env_var"] == "NVIDIA_API_KEY"
    assert "base_url" not in content["parameters"]
    main = next(m for m in config["models"] if m["type"] == "main")
    assert (
        "vllm-svc.llama-serving.svc.cluster.local:8000"
        in main["parameters"]["base_url"]
    )
    assert "api_key" not in main["parameters"]
    assert main["api_key_env_var"] == "OPENAI_API_KEY"


def _render_configmap(tmp_path, extra_env: str = "") -> dict:
    cluster_env = tmp_path / "cluster.env"
    cluster_env.write_text(
        CLUSTER_ENV_EXAMPLE.read_text(encoding="utf-8") + extra_env,
        encoding="utf-8",
    )
    output = tmp_path / "configmap.yaml"
    result = subprocess.run(
        [
            "python3",
            str(RENDER_SCRIPT),
            "--cluster-env",
            str(cluster_env),
            "--output",
            str(output),
        ],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(output.read_text(encoding="utf-8"))


def test_cluster_env_example_tracing_is_opt_in() -> None:
    text = CLUSTER_ENV_EXAMPLE.read_text(encoding="utf-8")
    assert not re.search(r"^GUARDRAILS_TRACING_ENABLED=", text, re.M)
    assert "# GUARDRAILS_TRACING_ENABLED=true" in text
    assert "tempo-guardrails-tracing.<ns>.svc.cluster.local:4317" in text
    assert "tempo-guardrails-tracing-distributor.<ns>.svc.cluster.local:4317" in text
    assert "tempo-stack-durable.yaml" in text
    assert "tempo-stack-production.yaml" not in text


def test_nemoguardrails_cr_has_otel_placeholders_not_tracing_flag() -> None:
    doc = yaml.safe_load(CR_MANIFEST.read_text(encoding="utf-8"))
    names = [entry["name"] for entry in doc["spec"]["env"]]
    assert "OPENAI_API_KEY" in names
    assert "NVIDIA_API_KEY" in names
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in names
    assert "OTEL_SERVICE_NAME" in names
    assert "OTEL_EXPORTER_OTLP_PROTOCOL" in names
    assert "OTEL_METRICS_EXPORTER" in names
    assert "GUARDRAILS_TRACING_ENABLED" not in names
    endpoint = next(
        e for e in doc["spec"]["env"] if e["name"] == "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    assert endpoint["value"] == "${OTEL_EXPORTER_OTLP_ENDPOINT}"


def _deploy_guardrails_recipe() -> str:
    match = re.search(
        r"^deploy-guardrails:.*?(?=^\S|\Z)",
        MAKEFILE,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    return match.group(0)


def test_deploy_guardrails_annotates_route_via_helper() -> None:
    recipe = _deploy_guardrails_recipe()
    assert "annotate_guardrails_route.py" in recipe
    assert "--route-name $(GUARDRAILS_CR_NAME)" in recipe
    assert '--namespace "$(GUARDRAILS_NAMESPACE)"' in recipe
    assert "$(if $(CI),--required,)" in recipe
    assert "oc annotate route" not in recipe


def test_makefile_deploy_targets_namespace() -> None:
    assert "GUARDRAILS_NAMESPACE   ?= $(shell oc project -q 2>/dev/null)" in MAKEFILE
    assert 'oc apply -n "$(GUARDRAILS_NAMESPACE)"' in MAKEFILE
    assert "oc delete nemoguardrails" in MAKEFILE
    assert "GUARDRAILS_KUSTOMIZE" not in MAKEFILE
    assert "oc delete -k" not in MAKEFILE
    assert "OTEL_EXPORTER_OTLP_PROTOCOL:-grpc" in MAKEFILE
    assert "ERROR: BASE_URL=" in MAKEFILE
    assert "finalize_nemoguardrails_cr.py" in MAKEFILE
    assert "command -v envsubst" in MAKEFILE
    assert (
        "$$OTEL_EXPORTER_OTLP_ENDPOINT $$OTEL_SERVICE_NAME "
        "$$OTEL_EXPORTER_OTLP_PROTOCOL $$OTEL_METRICS_EXPORTER" in MAKEFILE
    )


def test_gitignore_keeps_generated_and_secret_files_out() -> None:
    gitignore = (AGENT_DIR / ".gitignore").read_text(encoding="utf-8")
    assert "deploy/manifests/02-guardrails-configmap.yaml" in gitignore
    assert "deploy/tracing/object-storage-secret.yaml" in gitignore
    assert "deploy/overlays/ci-testing/cluster.env" in gitignore


def test_tracing_manifests_have_no_hardcoded_namespace() -> None:
    tracing_dir = DEPLOY_DIR / "tracing"
    yaml_files = sorted(tracing_dir.glob("*.yaml"))
    assert yaml_files, "expected tracing YAML manifests"
    names = {path.name for path in yaml_files}
    assert "minio-demo.yaml" in names
    assert "tempo-stack-durable.yaml" in names
    assert "tempo-stack-production.yaml" not in names
    assert "otel-collector-spanmetrics-stack.yaml" in names
    assert "otel-collector-spanmetrics-monolithic.yaml" in names
    assert "otel-collector-spanmetrics.yaml" not in names
    for path in yaml_files:
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if not doc:
                continue
            meta = doc.get("metadata") or {}
            assert "namespace" not in meta, (
                f"{path.name} hardcodes metadata.namespace={meta.get('namespace')!r}"
            )


def test_spanmetrics_stack_forwards_to_distributor() -> None:
    doc = yaml.safe_load(
        (DEPLOY_DIR / "tracing" / "otel-collector-spanmetrics-stack.yaml").read_text(
            encoding="utf-8"
        )
    )
    endpoint = doc["spec"]["config"]["exporters"]["otlp"]["endpoint"]
    assert "tempo-guardrails-tracing-distributor" in endpoint


def test_spanmetrics_monolithic_forwards_to_monolithic_service() -> None:
    doc = yaml.safe_load(
        (
            DEPLOY_DIR / "tracing" / "otel-collector-spanmetrics-monolithic.yaml"
        ).read_text(encoding="utf-8")
    )
    endpoint = doc["spec"]["config"]["exporters"]["otlp"]["endpoint"]
    assert endpoint.startswith("tempo-guardrails-tracing:")
    assert "distributor" not in endpoint


def test_finalize_cr_strips_otel_when_tracing_off(tmp_path, monkeypatch) -> None:
    script = DEPLOY_DIR / "scripts" / "finalize_nemoguardrails_cr.py"
    cr = tmp_path / "cr.yaml"
    cr.write_text(CR_MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.delenv("GUARDRAILS_TRACING_ENABLED", raising=False)
    result = subprocess.run(
        ["python3", str(script), str(cr)],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    doc = yaml.safe_load(cr.read_text(encoding="utf-8"))
    names = [e["name"] for e in doc["spec"]["env"]]
    assert names == ["OPENAI_API_KEY", "NVIDIA_API_KEY"]


def test_finalize_cr_keeps_otel_when_tracing_on(tmp_path, monkeypatch) -> None:
    script = DEPLOY_DIR / "scripts" / "finalize_nemoguardrails_cr.py"
    cr = tmp_path / "cr.yaml"
    text = CR_MANIFEST.read_text(encoding="utf-8").replace(
        "${OTEL_EXPORTER_OTLP_ENDPOINT}",
        "http://tempo-guardrails-tracing-distributor.demo.svc:4317",
    )
    cr.write_text(text, encoding="utf-8")
    monkeypatch.setenv("GUARDRAILS_TRACING_ENABLED", "true")
    result = subprocess.run(
        ["python3", str(script), str(cr)],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    doc = yaml.safe_load(cr.read_text(encoding="utf-8"))
    names = [e["name"] for e in doc["spec"]["env"]]
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in names
    by_name = {e["name"]: e.get("value") for e in doc["spec"]["env"] if "value" in e}
    assert by_name["OTEL_SERVICE_NAME"] == "nemo-guardrails"
    assert by_name["OTEL_EXPORTER_OTLP_PROTOCOL"] == "grpc"
    assert by_name["OTEL_METRICS_EXPORTER"] == "none"


def test_finalize_cr_defaults_empty_otel_when_tracing_on(tmp_path, monkeypatch) -> None:
    script = DEPLOY_DIR / "scripts" / "finalize_nemoguardrails_cr.py"
    cr = tmp_path / "cr.yaml"
    text = CR_MANIFEST.read_text(encoding="utf-8")
    text = text.replace(
        "${OTEL_EXPORTER_OTLP_ENDPOINT}",
        "http://tempo-guardrails-tracing.demo.svc:4317",
    )
    text = text.replace("${OTEL_SERVICE_NAME}", "")
    text = text.replace("${OTEL_EXPORTER_OTLP_PROTOCOL}", "")
    text = text.replace("${OTEL_METRICS_EXPORTER}", "")
    cr.write_text(text, encoding="utf-8")
    monkeypatch.setenv("GUARDRAILS_TRACING_ENABLED", "true")
    result = subprocess.run(
        ["python3", str(script), str(cr)],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    doc = yaml.safe_load(cr.read_text(encoding="utf-8"))
    by_name = {e["name"]: e.get("value") for e in doc["spec"]["env"] if "value" in e}
    assert by_name["OTEL_SERVICE_NAME"] == "nemo-guardrails"
    assert by_name["OTEL_EXPORTER_OTLP_PROTOCOL"] == "grpc"
    assert by_name["OTEL_METRICS_EXPORTER"] == "none"


def test_render_enables_tracing_when_flag_true(tmp_path) -> None:
    doc = _render_configmap(tmp_path, extra_env="\nGUARDRAILS_TRACING_ENABLED=true\n")
    config = yaml.safe_load(doc["data"]["config.yaml"])
    assert config["tracing"]["enabled"] is True
    assert config["tracing"]["enable_content_capture"] is False


def test_finalize_cr_fails_when_tracing_on_without_endpoint(
    tmp_path, monkeypatch
) -> None:
    script = DEPLOY_DIR / "scripts" / "finalize_nemoguardrails_cr.py"
    cr = tmp_path / "cr.yaml"
    cr.write_text(CR_MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("GUARDRAILS_TRACING_ENABLED", "true")
    result = subprocess.run(
        ["python3", str(script), str(cr)],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in result.stderr
