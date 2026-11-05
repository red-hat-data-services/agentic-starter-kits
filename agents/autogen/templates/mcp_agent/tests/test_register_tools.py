from __future__ import annotations

import importlib
import os
import ssl
import subprocess
import sys
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


@pytest.fixture
def register_tools(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(TEMPLATE_DIR))
    for var in ("DEPLOYMENT_URL", "DEPLOYMENT_TOKEN", "DEPLOYMENT_CA_BUNDLE"):
        monkeypatch.delenv(var, raising=False)
    return importlib.import_module("register_tools")


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


@pytest.mark.parametrize("custom_default", [False, True])
def test_ca_bundle_extends_httpx_trust(
    invoke_churn,
    captured_post,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    custom_default: bool,
) -> None:
    certificates = httpx.create_ssl_context(trust_env=False).get_ca_certs(
        binary_form=True
    )
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    if custom_default:
        default_bundle = tmp_path / "default-ca.pem"
        default_bundle.write_text(ssl.DER_cert_to_PEM_cert(certificates[0]))
        monkeypatch.setenv("SSL_CERT_FILE", str(default_bundle))
    default_roots = set(httpx.create_ssl_context().get_ca_certs(binary_form=True))
    additional_bundle = tmp_path / "additional-ca.pem"
    additional_bundle.write_text(ssl.DER_cert_to_PEM_cert(certificates[1]))
    monkeypatch.setenv(
        "DEPLOYMENT_URL", "https://m-predictor.ns.svc:8443/v1/models/m:predict"
    )
    monkeypatch.setenv("DEPLOYMENT_CA_BUNDLE", str(additional_bundle))

    invoke_churn(**CHURN_INPUT)

    context = captured_post["verify"]
    assert isinstance(context, ssl.SSLContext)
    trusted_roots = set(context.get_ca_certs(binary_form=True))
    assert default_roots <= trusted_roots
    assert certificates[1] in trusted_roots
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_without_ca_bundle_uses_system_trust(
    invoke_churn, captured_post, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "DEPLOYMENT_URL", "https://model.example.com/v1/models/m:predict"
    )

    invoke_churn(**CHURN_INPUT)

    assert captured_post["verify"] is True


def test_import_does_not_load_dotenv_or_pandas(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "DEPLOYMENT_URL=https://model.example.com/predict\n"
        "DEPLOYMENT_TOKEN=unit-test-token\n"
        "AUTOML_IMPORT_MARKER=loaded\n"
    )
    env = os.environ.copy()
    for var in ("DEPLOYMENT_URL", "DEPLOYMENT_TOKEN", "AUTOML_IMPORT_MARKER"):
        env.pop(var, None)
    env["PYTHONPATH"] = str(TEMPLATE_DIR)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sys\n"
            "before = dict(os.environ)\n"
            "import register_tools\n"
            "assert dict(os.environ) == before\n"
            "assert 'pandas' not in sys.modules\n",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
