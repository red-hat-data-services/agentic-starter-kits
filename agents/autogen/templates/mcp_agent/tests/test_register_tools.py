from __future__ import annotations

import importlib
import ssl
import sys
import types
from pathlib import Path
from typing import Any

import httpx
import pytest

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "mcp_automl_template"

CHURN_INPUT = {"tenure": 12, "Contract": "Month-to-month", "MonthlyCharges": 70.5}


class FakeMCP:
    """Captures handlers registered via ``mcp.tool(name=..., description=...)``."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, name: str, description: str):
        def decorator(fn):
            self.tools[name] = fn
            return fn

        return decorator


def _record_cafile(module, monkeypatch: pytest.MonkeyPatch, seen: list[str]) -> None:
    """Record the cafile passed to ssl.create_default_context without reading it."""
    real = ssl.create_default_context
    monkeypatch.setattr(
        module.ssl,
        "create_default_context",
        lambda cafile: seen.append(cafile) or real(),
    )


@pytest.fixture
def register_tools(monkeypatch: pytest.MonkeyPatch):
    # The template uses bare imports (``from utils import ...``) and utils imports
    # pandas, which the agent venv does not ship; stub it for the import only.
    monkeypatch.syspath_prepend(str(TEMPLATE_DIR))
    monkeypatch.setitem(sys.modules, "pandas", types.ModuleType("pandas"))
    for name in ("utils", "register_tools"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    for var in ("DEPLOYMENT_URL", "DEPLOYMENT_TOKEN", "DEPLOYMENT_CA_BUNDLE"):
        monkeypatch.delenv(var, raising=False)
    module = importlib.import_module("register_tools")
    # utils.load_dotenv() runs at import time and re-populates os.environ from a
    # developer's .env — scrub again so unit tests never hit a real deployment.
    for var in ("DEPLOYMENT_URL", "DEPLOYMENT_TOKEN", "DEPLOYMENT_CA_BUNDLE"):
        monkeypatch.delenv(var, raising=False)
    yield module
    for name in ("utils", "register_tools"):
        sys.modules.pop(name, None)


@pytest.fixture
def invoke_churn(register_tools):
    mcp = FakeMCP()
    register_tools.register_tools_from_config(mcp, TEMPLATE_DIR / "tools_config.yaml")
    return mcp.tools["invoke_churn"]


@pytest.fixture
def captured_post(register_tools, monkeypatch: pytest.MonkeyPatch):
    """Replace httpx.post; returns the dict the fake fills with call kwargs."""
    calls: dict[str, Any] = {"response": {"predictions": ["Yes"]}}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        calls["url"] = url
        calls.update(kwargs)
        return httpx.Response(
            200, json=calls["response"], request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(register_tools.httpx, "post", fake_post)
    return calls


def test_no_url_returns_validated_payload(invoke_churn, captured_post) -> None:
    out = invoke_churn(**CHURN_INPUT)

    assert isinstance(out, dict)
    assert out["tenure"] == 12
    assert out["gender"] is None
    assert "url" not in captured_post


def test_url_without_token_posts_without_auth_header(
    invoke_churn, captured_post, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "DEPLOYMENT_URL", "https://model.example.com/v1/models/m:predict"
    )

    out = invoke_churn(**CHURN_INPUT)

    assert captured_post["url"] == "https://model.example.com/v1/models/m:predict"
    assert "Authorization" not in captured_post["headers"]
    assert out == "Yes"


def test_url_and_token_send_bearer_header(
    invoke_churn, captured_post, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "DEPLOYMENT_URL", "https://model.example.com/v1/models/m:predict"
    )
    monkeypatch.setenv("DEPLOYMENT_TOKEN", "secret-token")

    invoke_churn(**CHURN_INPUT)

    assert captured_post["headers"]["Authorization"] == "Bearer secret-token"


def test_request_uses_kserve_v1_instances_shape(
    invoke_churn, captured_post, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "DEPLOYMENT_URL", "https://model.example.com/v1/models/m:predict"
    )

    invoke_churn(**CHURN_INPUT)

    (instance,) = captured_post["json"]["instances"]
    assert instance["tenure"] == [12]
    assert instance["Contract"] == ["Month-to-month"]
    assert instance["MonthlyCharges"] == [70.5]


def test_response_without_predictions_is_returned_verbatim(
    invoke_churn, captured_post, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "DEPLOYMENT_URL", "https://model.example.com/v1/models/m:predict"
    )
    captured_post["response"] = {"error": "unexpected"}

    assert invoke_churn(**CHURN_INPUT) == "{'error': 'unexpected'}"


def test_ca_bundle_env_is_passed_as_verify(
    invoke_churn, captured_post, register_tools, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    _record_cafile(register_tools, monkeypatch, seen)
    monkeypatch.setenv(
        "DEPLOYMENT_URL", "https://m-predictor.ns.svc:8443/v1/models/m:predict"
    )
    monkeypatch.setenv(
        "DEPLOYMENT_CA_BUNDLE",
        "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt",
    )

    invoke_churn(**CHURN_INPUT)

    assert seen == ["/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt"]
    assert isinstance(captured_post["verify"], ssl.SSLContext)


def test_without_ca_bundle_uses_system_trust(
    invoke_churn, captured_post, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "DEPLOYMENT_URL", "https://model.example.com/v1/models/m:predict"
    )

    invoke_churn(**CHURN_INPUT)

    assert captured_post["verify"] is True
