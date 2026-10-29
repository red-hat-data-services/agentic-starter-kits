"""Shared fixtures and helpers for guardrails integration tests."""

from __future__ import annotations

import os
import re

import httpx
import pytest

GUARDRAILS_BASE_URL = os.environ.get("GUARDRAILS_BASE_URL", "http://localhost:8090")
GUARDRAILS_PROFILE = os.environ.get("GUARDRAILS_PROFILE", "local")
GUARDRAILS_MODEL_ID = os.environ.get("GUARDRAILS_MODEL_ID", "llama3.1:8b")

GUARDRAILS_CHAT_TIMEOUT = float(os.environ.get("GUARDRAILS_CHAT_TIMEOUT", "120"))


def guardrails_tls_verify(base_url: str) -> bool:
    """Return whether httpx should verify TLS for a guardrails base URL."""
    override = os.environ.get("GUARDRAILS_TLS_VERIFY", "")
    if override.lower() in ("0", "false", "no"):
        return False
    if override.lower() in ("1", "true", "yes"):
        return True
    # OpenShift Routes use cluster-signed certs — skip verify by default for HTTPS.
    return not base_url.startswith("https://")


# Rail-block signatures only — not every apology or soft refusal from the LLM.
_RAIL_BLOCK_PATTERNS = re.compile(
    r"|".join(
        (
            r"i['']m sorry,?\s+i can'?t respond to that\.?",
            r"i can'?t respond to that\.?",
            r"blocked by\b.*\brails\b",
        )
    ),
    re.IGNORECASE,
)

_INTERNAL_ERROR_PATTERN = re.compile(r"an internal error has occurred", re.IGNORECASE)


def _extract_content(data: dict) -> str:
    """Return assistant message text from an OpenAI-style chat completion dict."""
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

    return bool(_RAIL_BLOCK_PATTERNS.search(content))


def is_allowed_response(data: dict, *, http_status: int | None = None) -> bool:
    """Return True for a substantive, non-refusal completion."""
    if http_status is not None and http_status != 200:
        return False
    content = _extract_content(data).strip()
    if len(content) <= 10:
        return False
    # NeMo's reply when a rail action raises: the request failed, it was not
    # answered (RHAIENG-7986).
    if _INTERNAL_ERROR_PATTERN.search(content):
        return False
    return not is_blocked_response(data, http_status=http_status)


def _post_guardrails(
    path: str,
    messages: list[dict[str, str]],
    *,
    profile: str | None,
    base_url: str | None,
    model_id: str | None,
    verify: bool | None,
    guardrails: dict | None = None,
    **extra_body,
) -> tuple[int, dict]:
    """POST an OpenAI-style request with a ``guardrails`` block to the proxy."""
    base = (base_url or GUARDRAILS_BASE_URL).rstrip("/")
    tls_verify = verify if verify is not None else guardrails_tls_verify(base)
    guardrails = dict(guardrails or {})
    config_id = profile if profile is not None else GUARDRAILS_PROFILE
    if config_id:
        guardrails["config_id"] = config_id
    body: dict = {
        "model": model_id or GUARDRAILS_MODEL_ID,
        "messages": messages,
        **extra_body,
    }
    if guardrails:
        body["guardrails"] = guardrails

    with httpx.Client(timeout=GUARDRAILS_CHAT_TIMEOUT, verify=tls_verify) as client:
        response = client.post(f"{base}{path}", json=body)
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"error": response.text}


def guardrails_chat(
    messages: list[dict[str, str]],
    *,
    profile: str | None = None,
    base_url: str | None = None,
    model_id: str | None = None,
    verify: bool | None = None,
) -> tuple[int, dict]:
    """POST to the NeMo Guardrails proxy OpenAI-compatible chat endpoint."""
    return _post_guardrails(
        "/v1/chat/completions",
        messages,
        profile=profile,
        base_url=base_url,
        model_id=model_id,
        verify=verify,
        stream=False,
    )


def guardrails_check(
    messages: list[dict[str, str]],
    *,
    profile: str | None = None,
    base_url: str | None = None,
    model_id: str | None = None,
    rail_types: list[str] | None = None,
    verify: bool | None = None,
) -> tuple[int, dict]:
    """POST to the NeMo Guardrails standalone ``/v1/checks`` endpoint.

    A 200 body is ``{"status": "passed"|"blocked", "content": ..., "rail": ...}``.
    """
    return _post_guardrails(
        "/v1/checks",
        messages,
        profile=profile,
        base_url=base_url,
        model_id=model_id,
        verify=verify,
        guardrails=None if rail_types is None else {"rail_types": rail_types},
    )


@pytest.fixture(scope="session")
def guardrails_server() -> str:
    """Ensure the NeMo Guardrails proxy is reachable; skip otherwise."""
    base = GUARDRAILS_BASE_URL.rstrip("/")
    try:
        with httpx.Client(timeout=10.0, verify=guardrails_tls_verify(base)) as client:
            response = client.get(f"{base}/v1/rails/configs")
            response.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        pytest.skip(f"Guardrails server unreachable at {base}: {exc}")
    return base


@pytest.fixture(scope="session")
def expected_config_id() -> str:
    """Profile name expected in guardrails.config_id responses."""
    return GUARDRAILS_PROFILE
