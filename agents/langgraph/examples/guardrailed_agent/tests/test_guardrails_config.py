"""Structural tests for NeMo Guardrails configuration files.

Validates that both the `local` and `nemoguard` guardrails config profiles are
well-formed and contain their required components, without needing a
running LLM or NeMo server.
"""

from pathlib import Path

import pytest
import yaml

AGENT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = AGENT_DIR / "guardrails" / "config"
PROFILES = ("local", "nemoguard")


@pytest.mark.parametrize("profile", PROFILES)
class TestConfigFilesExist:
    def test_config_yaml_example_exists(self, profile):
        assert (CONFIG_DIR / profile / "config.yaml.example").is_file()

    def test_config_uses_yaml_extension_not_yml(self, profile):
        profile_dir = CONFIG_DIR / profile
        assert not (profile_dir / "config.yml").exists()
        assert not (profile_dir / "config.yml.example").exists()

    def test_prompts_yml_exists(self, profile):
        assert (CONFIG_DIR / profile / "prompts.yml").is_file()

    def test_rails_co_exists(self, profile):
        assert (CONFIG_DIR / profile / "rails.co").is_file()


@pytest.mark.parametrize("profile", PROFILES)
class TestRailsCo:
    def test_rails_co_is_not_empty(self, profile):
        content = (CONFIG_DIR / profile / "rails.co").read_text(encoding="utf-8")
        assert len(content.strip()) > 0

    def test_rails_co_defines_greeting_flow(self, profile):
        content = (CONFIG_DIR / profile / "rails.co").read_text(encoding="utf-8")
        assert "express greeting" in content


class TestLocalConfigYaml:
    @classmethod
    def setup_class(cls):
        cls.config = yaml.safe_load(
            (CONFIG_DIR / "local" / "config.yaml.example").read_text(encoding="utf-8")
        )

    def test_has_single_main_model(self):
        model_types = [m["type"] for m in self.config["models"]]
        assert model_types == ["main"]

    def test_passthrough_enabled(self):
        assert self.config.get("passthrough") is True

    def test_has_self_check_rails(self):
        input_flows = self.config["rails"]["input"]["flows"]
        output_flows = self.config["rails"]["output"]["flows"]
        assert "self check input" in input_flows
        assert "self check output" in output_flows

    def test_has_regex_input_rail(self):
        assert "regex check input" in self.config["rails"]["input"]["flows"]

    def test_streaming_enabled(self):
        assert self.config["rails"]["output"]["streaming"]["enabled"] is True


class TestLocalPromptsYml:
    @classmethod
    def setup_class(cls):
        cls.prompts = yaml.safe_load(
            (CONFIG_DIR / "local" / "prompts.yml").read_text(encoding="utf-8")
        )

    def test_has_self_check_input_prompt(self):
        tasks = [p["task"] for p in self.prompts["prompts"]]
        assert "self_check_input" in tasks

    def test_has_self_check_output_prompt(self):
        tasks = [p["task"] for p in self.prompts["prompts"]]
        assert "self_check_output" in tasks


class TestNemoguardConfigYaml:
    @classmethod
    def setup_class(cls):
        cls.config = yaml.safe_load(
            (CONFIG_DIR / "nemoguard" / "config.yaml.example").read_text(
                encoding="utf-8"
            )
        )

    def test_has_models_section(self):
        assert "models" in self.config
        model_types = {m["type"] for m in self.config["models"]}
        assert "main" in model_types
        assert "content_safety" in model_types
        assert "topic_control" in model_types

    def test_passthrough_enabled(self):
        assert self.config.get("passthrough") is True

    def test_has_input_rails(self):
        flows = self.config["rails"]["input"]["flows"]
        flow_text = " ".join(flows)
        assert "content safety check input" in flow_text
        assert "topic safety check input" in flow_text

    def test_has_regex_input_rail(self):
        flows = self.config["rails"]["input"]["flows"]
        assert "regex check input" in flows

    def test_has_output_rails(self):
        flows = self.config["rails"]["output"]["flows"]
        flow_text = " ".join(flows)
        assert "content safety check output" in flow_text

    def test_streaming_enabled(self):
        assert self.config["rails"]["output"]["streaming"]["enabled"] is True

    def test_regex_patterns_configured(self):
        patterns = self.config["rails"]["config"]["regex_detection"]["input"][
            "patterns"
        ]
        assert len(patterns) >= 1
        joined = "\n".join(patterns)
        assert "ignore" in joined.lower()
        assert "DAN" in joined


class TestNemoguardPromptsYml:
    @classmethod
    def setup_class(cls):
        cls.prompts = yaml.safe_load(
            (CONFIG_DIR / "nemoguard" / "prompts.yml").read_text(encoding="utf-8")
        )

    def test_has_content_safety_input_prompt(self):
        tasks = [p["task"] for p in self.prompts["prompts"]]
        assert any("content_safety_check_input" in t for t in tasks)

    def test_has_content_safety_output_prompt(self):
        tasks = [p["task"] for p in self.prompts["prompts"]]
        assert any("content_safety_check_output" in t for t in tasks)

    def test_has_topic_safety_prompt(self):
        tasks = [p["task"] for p in self.prompts["prompts"]]
        assert any("topic_safety_check_input" in t for t in tasks)

    def test_input_prompt_uses_correct_output_parser(self):
        for p in self.prompts["prompts"]:
            if "content_safety_check_input" in p["task"]:
                assert p["output_parser"] == "nemoguard_parse_prompt_safety"

    def test_output_prompt_uses_correct_output_parser(self):
        for p in self.prompts["prompts"]:
            if "content_safety_check_output" in p["task"]:
                assert p["output_parser"] == "nemoguard_parse_response_safety"

    def test_topic_prompt_mentions_banking(self):
        for p in self.prompts["prompts"]:
            if "topic_safety_check_input" in p["task"]:
                content = p["content"].lower()
                assert "bank" in content

    def test_s9_does_not_treat_bank_account_ids_as_pii(self):
        for p in self.prompts["prompts"]:
            if "content_safety_check_input" in p["task"]:
                content = p["content"]
                assert "ACCT-12345" in content
                assert "S9: PII/Privacy" in content
