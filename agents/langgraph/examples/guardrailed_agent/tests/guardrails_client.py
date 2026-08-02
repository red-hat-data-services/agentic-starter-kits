"""Importable re-exports of guardrails helpers defined in tests/conftest.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_TESTS_CONFTEST = Path(__file__).resolve().parent / "conftest.py"
_spec = importlib.util.spec_from_file_location(
    "guardrails_tests_conftest", _TESTS_CONFTEST
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load guardrails test conftest at {_TESTS_CONFTEST}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

GUARDRAILS_BASE_URL = _mod.GUARDRAILS_BASE_URL
GUARDRAILS_MODEL_ID = _mod.GUARDRAILS_MODEL_ID
GUARDRAILS_PROFILE = _mod.GUARDRAILS_PROFILE
guardrails_chat = _mod.guardrails_chat
is_allowed_response = _mod.is_allowed_response
is_blocked_response = _mod.is_blocked_response

__all__ = [
    "GUARDRAILS_BASE_URL",
    "GUARDRAILS_MODEL_ID",
    "GUARDRAILS_PROFILE",
    "guardrails_chat",
    "is_allowed_response",
    "is_blocked_response",
]
