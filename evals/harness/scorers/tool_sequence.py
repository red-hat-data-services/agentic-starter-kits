"""Scorers for tool selection, sequencing, validity, and hallucination detection."""

from __future__ import annotations

import json

from harness.runner import TaskResult
from harness.scorers import Score


def score_tool_sequence(result: TaskResult, expected_tools: list[str]) -> Score:
    """Check if tools were called in the expected order.

    Uses longest common subsequence to measure how well the actual
    tool call order matches the expected sequence.
    """
    actual = [tc["name"] for tc in result.tool_calls]

    if not expected_tools:
        return Score(
            name="tool_sequence",
            value=1.0 if not actual else 0.0,
            passed=not actual,
            details={"expected": expected_tools, "actual": actual},
        )

    if not actual:
        return Score(
            name="tool_sequence",
            value=0.0,
            passed=False,
            details={
                "expected": expected_tools,
                "actual": actual,
                "reason": "no tool calls found",
            },
        )

    # Longest common subsequence length
    lcs_len = _lcs_length(expected_tools, actual)
    value = lcs_len / len(expected_tools)
    passed = actual == expected_tools

    return Score(
        name="tool_sequence",
        value=value,
        passed=passed,
        details={
            "expected": expected_tools,
            "actual": actual,
            "lcs_length": lcs_len,
            "exact_match": passed,
        },
    )


def _lcs_length(a: list[str], b: list[str]) -> int:
    """Compute the length of the longest common subsequence."""
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[m][n]


def score_tool_selection(result: TaskResult, expected_tools: list[str]) -> Score:
    """Check if the correct tools were selected, regardless of order.

    Measures set overlap between expected and actual tools.
    """
    actual = [tc["name"] for tc in result.tool_calls]
    expected_set = set(expected_tools)
    actual_set = set(actual)

    if not expected_set:
        value = 1.0 if not actual_set else 0.0
        return Score(
            name="tool_selection",
            value=value,
            passed=value == 1.0,
            details={"expected": sorted(expected_set), "actual": sorted(actual_set)},
        )

    intersection = expected_set & actual_set
    # F1-style: harmonic mean of precision and recall
    precision = len(intersection) / len(actual_set) if actual_set else 0.0
    recall = len(intersection) / len(expected_set)
    if precision + recall == 0:
        value = 0.0
    else:
        value = 2 * precision * recall / (precision + recall)

    passed = expected_set == actual_set

    return Score(
        name="tool_selection",
        value=value,
        passed=passed,
        details={
            "expected": sorted(expected_set),
            "actual": sorted(actual_set),
            "missing": sorted(expected_set - actual_set),
            "extra": sorted(actual_set - expected_set),
            "precision": precision,
            "recall": recall,
        },
    )


def score_tool_call_validity(result: TaskResult) -> Score:
    """Check that all tool calls have valid JSON arguments."""
    if not result.tool_calls:
        return Score(
            name="tool_call_validity",
            value=1.0,
            passed=True,
            details={"reason": "no tool calls to validate"},
        )

    invalid: list[dict] = []
    for tc in result.tool_calls:
        args = tc.get("arguments")
        if args is None:
            pass  # None is valid for parameterless tools
        elif isinstance(args, str):
            try:
                json.loads(args)
            except json.JSONDecodeError:
                invalid.append(
                    {"tool": tc["name"], "reason": "arguments not valid JSON"}
                )
        elif isinstance(args, dict):
            # Check for raw unparseable args from extraction
            if "_raw" in args:
                invalid.append(
                    {"tool": tc["name"], "reason": "arguments failed JSON parsing"}
                )

    valid_count = len(result.tool_calls) - len(invalid)
    value = valid_count / len(result.tool_calls)

    return Score(
        name="tool_call_validity",
        value=value,
        passed=len(invalid) == 0,
        details={
            "total_calls": len(result.tool_calls),
            "valid_calls": valid_count,
            "invalid": invalid,
        },
    )


def score_hallucinated_tools(result: TaskResult, known_tools: list[str]) -> Score:
    """Detect tool calls to tools that do not exist in the agent's schema."""
    if not result.tool_calls:
        return Score(
            name="hallucinated_tools",
            value=1.0,
            passed=True,
            details={"reason": "no tool calls"},
        )

    known_set = set(known_tools)
    hallucinated = [
        tc["name"] for tc in result.tool_calls if tc["name"] not in known_set
    ]

    legitimate_count = len(result.tool_calls) - len(hallucinated)
    value = legitimate_count / len(result.tool_calls)

    return Score(
        name="hallucinated_tools",
        value=value,
        passed=len(hallucinated) == 0,
        details={
            "total_calls": len(result.tool_calls),
            "hallucinated": hallucinated,
            "known_tools": sorted(known_set),
        },
    )
