"""Structural tests for NeMo Guardrails configuration files.

Validates that the guardrails config is well-formed and contains all
required components without needing a running LLM or NeMo server.
"""

from pathlib import Path

import yaml

AGENT_DIR = Path(__file__).resolve().parents[1]
GUARDRAILS_DIR = AGENT_DIR / "guardrails" / "safety"


class TestConfigFilesExist:
    def test_config_yaml_exists(self):
        assert (GUARDRAILS_DIR / "config.yaml").is_file()

    def test_config_uses_yaml_extension_not_yml(self):
        assert (GUARDRAILS_DIR / "config.yaml").is_file()
        assert not (GUARDRAILS_DIR / "config.yml").exists()

    def test_prompts_yml_exists(self):
        assert (GUARDRAILS_DIR / "prompts.yml").is_file()

    def test_rails_co_exists(self):
        assert (GUARDRAILS_DIR / "rails.co").is_file()


class TestConfigYaml:
    @classmethod
    def setup_class(cls):
        cls.config = yaml.safe_load(
            (GUARDRAILS_DIR / "config.yaml").read_text(encoding="utf-8")
        )

    def test_has_models_section(self):
        assert "models" in self.config
        model_types = {m["type"] for m in self.config["models"]}
        assert "main" in model_types
        assert "content_safety" in model_types

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


class TestPromptsYml:
    @classmethod
    def setup_class(cls):
        cls.prompts = yaml.safe_load(
            (GUARDRAILS_DIR / "prompts.yml").read_text(encoding="utf-8")
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
                assert "bank" in p["content"].lower()


class TestRailsCo:
    def test_rails_co_is_not_empty(self):
        content = (GUARDRAILS_DIR / "rails.co").read_text(encoding="utf-8")
        assert len(content.strip()) > 0

    def test_rails_co_defines_greeting_flow(self):
        content = (GUARDRAILS_DIR / "rails.co").read_text(encoding="utf-8")
        assert "express greeting" in content
