"""Unit tests for guardrails/generate_config.py.

Covers the per-role model/engine override logic and the topic_control
"custom policy" auto-detection that swaps in the topic_policy.co flow for
models like nvidia/nemotron-3.5-content-safety (nemoguard profile), plus basic
sanity checks that both the local and nemoguard config.yaml.example templates
generate valid config.yaml files.
"""

import importlib.util
import shutil
from pathlib import Path

import pytest
import yaml

AGENT_DIR = Path(__file__).resolve().parents[1]
GUARDRAILS_DIR = AGENT_DIR / "guardrails"
CONFIG_DIR = GUARDRAILS_DIR / "config"
SCRIPT_PATH = GUARDRAILS_DIR / "generate_config.py"


def _load_generate_config_module():
    spec = importlib.util.spec_from_file_location("generate_config", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generate_config = _load_generate_config_module()

# Every env var generate_config.py reads, so tests are never affected by
# whatever's leaked into the ambient shell (e.g. from `source .env`).
_ALL_OVERRIDE_ENV_VARS = [
    "MODEL_ID",
    "LLM_BASE_URL",
    "API_KEY",
    "TOPIC_CONTROL_CUSTOM_POLICY",
] + [
    f"{prefix}_{suffix}"
    for prefix in generate_config._ROLE_ENV_PREFIX.values()
    for suffix in ("MODEL_ID", "LLM_BASE_URL", "API_KEY", "MODEL_ENGINE")
]


@pytest.fixture(autouse=True)
def _clean_guardrails_env(monkeypatch):
    """Clears all generate_config.py-relevant env vars before every test in
    this module, so ambient shell state (e.g. a previously-sourced .env)
    can't leak into assertions about default behavior."""
    for var in _ALL_OVERRIDE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


class TestTopicControlCustomPolicy:
    def test_no_override_for_generic_instruct_model(self, monkeypatch):
        monkeypatch.delenv("TOPIC_CONTROL_CUSTOM_POLICY", raising=False)
        assert (
            generate_config._topic_control_custom_policy("meta/llama-3.1-8b-instruct")
            is None
        )

    def test_auto_detects_nemotron_3_5_content_safety(self, monkeypatch):
        monkeypatch.delenv("TOPIC_CONTROL_CUSTOM_POLICY", raising=False)
        policy = generate_config._topic_control_custom_policy(
            "nvidia/nemotron-3.5-content-safety"
        )
        assert policy == generate_config._DEFAULT_TOPIC_CONTROL_POLICY

    def test_auto_detects_content_safety_reasoning_model(self, monkeypatch):
        monkeypatch.delenv("TOPIC_CONTROL_CUSTOM_POLICY", raising=False)
        policy = generate_config._topic_control_custom_policy(
            "nvidia/nemotron-content-safety-reasoning-4b"
        )
        assert policy is not None

    def test_explicit_env_override_wins_over_auto_detection(self, monkeypatch):
        monkeypatch.setenv("TOPIC_CONTROL_CUSTOM_POLICY", "Only talk about widgets.")
        policy = generate_config._topic_control_custom_policy(
            "meta/llama-3.1-8b-instruct"
        )
        assert policy == "Only talk about widgets."

    def test_explicit_env_override_applies_even_for_matching_model(self, monkeypatch):
        monkeypatch.setenv("TOPIC_CONTROL_CUSTOM_POLICY", "Custom text.")
        policy = generate_config._topic_control_custom_policy(
            "nvidia/nemotron-3.5-content-safety"
        )
        assert policy == "Custom text."


@pytest.fixture()
def generated_config(tmp_path, monkeypatch):
    """Runs generate_config.generate_config() against a scratch copy of a
    profile's config.yaml.example."""

    def _generate(profile: str, env: dict) -> dict:
        config_path = tmp_path / f"{profile}-config.yaml"
        shutil.copy(CONFIG_DIR / profile / "config.yaml.example", config_path)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        generate_config.generate_config(str(config_path))
        return yaml.safe_load(config_path.read_text(encoding="utf-8"))

    return _generate


class TestGenerateConfigMain:
    def test_default_env_keeps_builtin_topic_flow(self, generated_config):
        config = generated_config(
            "nemoguard",
            {"MODEL_ID": "llama3.1:8b", "LLM_BASE_URL": "http://x", "API_KEY": "k"},
        )
        flows = config["rails"]["input"]["flows"]
        assert "topic safety check input $model=topic_control" in flows
        assert "topic policy check input $model=topic_control" not in flows
        topic_model = next(m for m in config["models"] if m["type"] == "topic_control")
        assert "chat_template_kwargs" not in topic_model["parameters"]

    def test_nemotron_3_5_content_safety_swaps_flow_and_injects_policy(
        self, generated_config
    ):
        config = generated_config(
            "nemoguard",
            {
                "MODEL_ID": "llama3.1:8b",
                "LLM_BASE_URL": "http://x",
                "API_KEY": "k",
                "TOPIC_CONTROL_MODEL_ID": "nvidia/nemotron-3.5-content-safety",
                "TOPIC_CONTROL_MODEL_ENGINE": "nim",
            },
        )
        flows = config["rails"]["input"]["flows"]
        assert "topic policy check input $model=topic_control" in flows
        assert "topic safety check input $model=topic_control" not in flows

        topic_model = next(m for m in config["models"] if m["type"] == "topic_control")
        assert topic_model["model"] == "nvidia/nemotron-3.5-content-safety"
        assert topic_model["engine"] == "nim"
        assert topic_model["parameters"]["chat_template_kwargs"]["custom_policy"]
        assert (
            topic_model["parameters"]["chat_template_kwargs"]["enable_thinking"]
            is False
        )

    def test_other_roles_unaffected_by_topic_control_custom_policy(
        self, generated_config
    ):
        config = generated_config(
            "nemoguard",
            {
                "MODEL_ID": "llama3.1:8b",
                "LLM_BASE_URL": "http://x",
                "API_KEY": "k",
                "TOPIC_CONTROL_MODEL_ID": "nvidia/nemotron-3.5-content-safety",
            },
        )
        for role in ("main", "content_safety"):
            model = next(m for m in config["models"] if m["type"] == role)
            assert "chat_template_kwargs" not in model["parameters"]

    def test_local_profile_generates_single_main_role_with_self_check(
        self, generated_config
    ):
        config = generated_config(
            "local",
            {"MODEL_ID": "llama3.1:8b", "LLM_BASE_URL": "http://x", "API_KEY": "k"},
        )
        assert [m["type"] for m in config["models"]] == ["main"]
        main_model = config["models"][0]
        assert main_model["model"] == "llama3.1:8b"
        assert main_model["parameters"]["base_url"] == "http://x"

        input_flows = config["rails"]["input"]["flows"]
        output_flows = config["rails"]["output"]["flows"]
        assert "self check input" in input_flows
        assert "self check output" in output_flows


class TestGenerateConfigValidation:
    def test_missing_models_raises(self, tmp_path):
        config_path = tmp_path / "bad.yaml"
        config_path.write_text("passthrough: true\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing top-level 'models'"):
            generate_config.generate_config(str(config_path))

    def test_missing_model_type_raises(self, tmp_path):
        config_path = tmp_path / "bad.yaml"
        config_path.write_text(
            "models:\n  - engine: openai\n    parameters: {}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="missing 'type'"):
            generate_config.generate_config(str(config_path))

    def test_missing_parameters_raises(self, tmp_path):
        config_path = tmp_path / "bad.yaml"
        config_path.write_text(
            "models:\n  - type: main\n    engine: openai\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="missing 'parameters'"):
            generate_config.generate_config(str(config_path))

    def test_missing_rails_input_flows_raises(self, tmp_path, monkeypatch):
        config_path = tmp_path / "bad.yaml"
        shutil.copy(CONFIG_DIR / "nemoguard" / "config.yaml.example", config_path)
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        del cfg["rails"]["input"]["flows"]
        config_path.write_text(yaml.dump(cfg), encoding="utf-8")
        monkeypatch.setenv(
            "TOPIC_CONTROL_MODEL_ID", "nvidia/nemotron-3.5-content-safety"
        )
        with pytest.raises(ValueError, match="missing rails.input.flows"):
            generate_config.generate_config(str(config_path))

    def test_custom_topic_flow_without_builtin_raises(self, tmp_path, monkeypatch):
        config_path = tmp_path / "bad.yaml"
        shutil.copy(CONFIG_DIR / "nemoguard" / "config.yaml.example", config_path)
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        cfg["rails"]["input"]["flows"] = [
            flow
            for flow in cfg["rails"]["input"]["flows"]
            if "topic safety check input" not in flow
        ]
        config_path.write_text(yaml.dump(cfg), encoding="utf-8")
        monkeypatch.setenv(
            "TOPIC_CONTROL_MODEL_ID", "nvidia/nemotron-3.5-content-safety"
        )
        with pytest.raises(ValueError, match="expected flow"):
            generate_config.generate_config(str(config_path))


def _load_actions_module():
    actions_path = CONFIG_DIR / "nemoguard" / "actions.py"
    spec = importlib.util.spec_from_file_location("nemoguard_actions", actions_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTopicPolicyVerdictParsing:
    def test_safe_with_caveats_is_not_treated_as_safe(self):
        actions = _load_actions_module()
        assert (
            actions._parse_user_safety_verdict('{"User Safety": "safe_with_caveats"}')
            is False
        )

    def test_explicit_safe_verdict_is_allowed(self):
        actions = _load_actions_module()
        assert actions._parse_user_safety_verdict("User Safety: safe") is True
