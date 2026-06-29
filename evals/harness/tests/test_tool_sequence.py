"""Unit tests for tool sequence scorers and name normalization."""

from __future__ import annotations

import pytest

from harness.runner import TaskResult
from harness.scorers.tool_sequence import (
    _normalize_tool_name,
    score_hallucinated_tools,
    score_tool_selection,
    score_tool_sequence,
)


def _result(tool_names: list[str]) -> TaskResult:
    return TaskResult(
        response="ok",
        tool_calls=[{"name": n, "arguments": None} for n in tool_names],
        latency_seconds=0.1,
        tokens_used=None,
        raw_response={},
        success=True,
    )


# ---------------------------------------------------------------------------
# _normalize_tool_name
# ---------------------------------------------------------------------------


class TestNormalizeToolName:
    def test_lowercase(self):
        assert _normalize_tool_name("WebSearch") == "websearch"

    def test_spaces_to_underscores(self):
        assert _normalize_tool_name("Web Search") == "web_search"

    def test_hyphens_to_underscores(self):
        assert _normalize_tool_name("web-search") == "web_search"

    def test_mixed(self):
        assert _normalize_tool_name("Web-Search Tool") == "web_search_tool"

    def test_already_normalized(self):
        assert _normalize_tool_name("web_search") == "web_search"

    def test_none(self):
        assert _normalize_tool_name(None) == ""

    def test_empty_string(self):
        assert _normalize_tool_name("") == ""

    def test_consecutive_separators(self):
        assert _normalize_tool_name("web--search") == "web__search"


# ---------------------------------------------------------------------------
# score_tool_sequence — normalization
# ---------------------------------------------------------------------------


class TestScoreToolSequenceNormalization:
    def test_case_insensitive_match(self):
        result = _result(["Web_Search"])
        score = score_tool_sequence(result, ["web_search"])
        assert score.passed

    def test_hyphen_space_match(self):
        result = _result(["Web Search"])
        score = score_tool_sequence(result, ["web-search"])
        assert score.passed
        assert score.value == 1.0

    def test_mismatch_still_fails(self):
        result = _result(["read_file"])
        score = score_tool_sequence(result, ["web_search"])
        assert not score.passed


# ---------------------------------------------------------------------------
# score_tool_selection — normalization
# ---------------------------------------------------------------------------


class TestScoreToolSelectionNormalization:
    def test_display_name_matches_snake_case(self):
        result = _result(["Web Search", "Read File"])
        score = score_tool_selection(result, ["web_search", "read_file"])
        assert score.passed
        assert score.value == 1.0

    def test_extra_tool_detected_after_normalization(self):
        result = _result(["Web Search", "extra-tool"])
        score = score_tool_selection(result, ["web_search"])
        assert not score.passed
        assert "extra_tool" in score.details["extra"]


# ---------------------------------------------------------------------------
# score_hallucinated_tools — normalization
# ---------------------------------------------------------------------------


class TestScoreHallucinatedToolsNormalization:
    def test_known_tool_not_flagged(self):
        result = _result(["Web Search"])
        score = score_hallucinated_tools(result, ["web_search"])
        assert score.passed
        assert score.details["hallucinated"] == []

    def test_unknown_tool_flagged(self):
        result = _result(["Web Search", "HackTool"])
        score = score_hallucinated_tools(result, ["web_search"])
        assert not score.passed
        assert "HackTool" in score.details["hallucinated"]

    @pytest.mark.parametrize(
        ("actual", "known"),
        [
            ("Web-Search", "web_search"),
            ("WEB SEARCH", "web-search"),
            ("web_search", "Web Search"),
        ],
    )
    def test_variant_pairs(self, actual: str, known: str):
        result = _result([actual])
        score = score_hallucinated_tools(result, [known])
        assert score.passed
