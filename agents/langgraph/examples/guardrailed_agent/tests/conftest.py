"""Shared fixtures and helpers for guardrails integration tests."""

from __future__ import annotations

import os
import re

import httpx
import pytest

GUARDRAILS_BASE_URL = os.environ.get("GUARDRAILS_BASE_URL", "http://localhost:8090")
GUARDRAILS_PROFILE = os.environ.get("GUARDRAILS_PROFILE", "local")
GUARDRAILS_MODEL_ID = os.environ.get("GUARDRAILS_MODEL_ID", "llama3.1:8b")

GUARDRAILS_CHAT_TIMEOUT = 120.0

_REFUSAL_PATTERNS = re.compile(r"\b(sorry|can't|cannot)\b", re.IGNORECASE)
_BANKING_HINTS = re.compile(
    r"\b(balance|account|bank|acct|transaction|deposit|withdraw)\b", re.IGNORECASE
)


def _extract_content(data: dict) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    return content if isinstance(content, str) else ""


def is_blocked_response(data: dict, *, http_status: int | None = None) -> bool:
    """Return True when the guardrails proxy refused or errored on the request."""
    if http_status is not None and 400 <= http_status < 500:
        return True
    if "error" in data:
        return True

    content = _extract_content(data).strip()
    if not content:
        return True

    if len(content) > 50 and _BANKING_HINTS.search(content):
        return False

    return bool(_REFUSAL_PATTERNS.search(content))


def is_allowed_response(data: dict, *, http_status: int | None = None) -> bool:
    """Return True for a substantive, non-refusal completion."""
    if http_status is not None and http_status != 200:
        return False
    content = _extract_content(data).strip()
    if len(content) <= 10:
        return False
    return not is_blocked_response(data, http_status=http_status)


def guardrails_chat(
    messages: list[dict[str, str]],
    *,
    profile: str | None = None,
) -> tuple[int, dict]:
    """POST to the NeMo Guardrails proxy OpenAI-compatible chat endpoint."""
    base = GUARDRAILS_BASE_URL.rstrip("/")
    body: dict = {
        "model": GUARDRAILS_MODEL_ID,
        "messages": messages,
        "stream": False,
    }
    config_id = profile if profile is not None else GUARDRAILS_PROFILE
    if config_id:
        body["guardrails"] = {"config_id": config_id}

    with httpx.Client(timeout=GUARDRAILS_CHAT_TIMEOUT) as client:
        response = client.post(f"{base}/v1/chat/completions", json=body)
        try:
            data = response.json()
        except ValueError:
            data = {"error": response.text}
        return response.status_code, data


@pytest.fixture(scope="session")
def guardrails_server() -> str:
    """Ensure the NeMo Guardrails proxy is reachable; skip otherwise."""
    base = GUARDRAILS_BASE_URL.rstrip("/")
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{base}/v1/rails/configs")
            response.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        pytest.skip(f"Guardrails server unreachable at {base}: {exc}")
    return base


@pytest.fixture(scope="session")
def expected_config_id() -> str:
    return GUARDRAILS_PROFILE
