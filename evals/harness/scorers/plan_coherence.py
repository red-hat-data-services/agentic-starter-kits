"""Scorers for plan coherence and response completeness."""

from __future__ import annotations

import re

from harness.runner import TaskResult
from harness.scorers import Score


def score_plan_coherence(result: TaskResult) -> Score:
    """Basic heuristic check for response quality.

    Checks that the response:
    - Is non-empty
    - Has meaningful length (>50 chars)
    - Contains structure (numbered lists, bullets, or sections)
    - Contains actionable content (not just filler)
    """
    text = result.response.strip()

    if not text:
        return Score(
            name="plan_coherence",
            value=0.0,
            passed=False,
            details={"reason": "empty response"},
        )

    checks: dict[str, bool] = {}
    scores: list[float] = []

    # Minimum length
    checks["has_meaningful_length"] = len(text) > 50
    scores.append(1.0 if checks["has_meaningful_length"] else 0.2)

    # Has structure (bullets, numbered lists, headers, or paragraphs)
    structure_patterns = [
        r"^\s*[-*]\s",  # bullet points
        r"^\s*\d+[.)]\s",  # numbered lists
        r"^#+\s",  # markdown headers
        r"\n\n",  # paragraph breaks
    ]
    checks["has_structure"] = any(
        re.search(p, text, re.MULTILINE) for p in structure_patterns
    )
    scores.append(1.0 if checks["has_structure"] else 0.3)

    # Has multiple sentences (not a one-liner)
    sentence_count = len(re.findall(r"[.!?]+\s", text)) + 1
    checks["has_multiple_sentences"] = sentence_count >= 2
    scores.append(1.0 if checks["has_multiple_sentences"] else 0.5)

    # Not predominantly error/refusal
    refusal_patterns = [
        r"i (?:can't|cannot|don't|am unable to)",
        r"i'm sorry",
        r"as an ai",
    ]
    is_refusal = any(re.search(p, text.lower()) for p in refusal_patterns)
    checks["not_refusal"] = not is_refusal
    scores.append(1.0 if checks["not_refusal"] else 0.0)

    value = sum(scores) / len(scores)
    passed = value >= 0.6

    return Score(
        name="plan_coherence",
        value=value,
        passed=passed,
        details={"checks": checks, "sentence_count": sentence_count},
    )


def score_completeness(result: TaskResult, required_elements: list[str]) -> Score:
    """Check that the response contains all required elements.

    Each element is checked case-insensitively as a substring of the response.
    """
    text = result.response.lower()

    if not required_elements:
        return Score(
            name="completeness",
            value=1.0,
            passed=True,
            details={"reason": "no required elements specified"},
        )

    found: list[str] = []
    missing: list[str] = []

    for element in required_elements:
        if element.lower() in text:
            found.append(element)
        else:
            missing.append(element)

    value = len(found) / len(required_elements)
    passed = len(missing) == 0

    return Score(
        name="completeness",
        value=value,
        passed=passed,
        details={
            "required": required_elements,
            "found": found,
            "missing": missing,
        },
    )
