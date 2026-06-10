from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

SATokenAuthMiddleware = pytest.importorskip(
    "agent_auth.middleware"
).SATokenAuthMiddleware


async def _health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


async def _chat(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _build_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth_enabled: str = "true",
    allowlist: str = "ci-testing:allowed-caller",
) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", auth_enabled)
    monkeypatch.setenv("AUTH_AUDIENCE", "langgraph-react-agent")
    monkeypatch.setenv("AUTH_EXCLUDE_PATHS", "/health")
    monkeypatch.setenv("AUTH_ALLOWED_SERVICEACCOUNTS", allowlist)

    app = Starlette(
        routes=[
            Route("/health", _health),
            Route("/chat/completions", _chat, methods=["POST"]),
        ]
    )
    app.add_middleware(SATokenAuthMiddleware)
    return TestClient(app)


def _review(username: str, *, authenticated: bool = True):
    return SimpleNamespace(
        status=SimpleNamespace(
            authenticated=authenticated,
            user=SimpleNamespace(username=username),
        )
    )


def test_auth_disabled_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    with _build_client(monkeypatch, auth_enabled="false") as client:
        response = client.post("/chat/completions", json={"messages": []})
    assert response.status_code == 200


def test_health_path_bypasses_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    with _build_client(monkeypatch) as client:
        response = client.get("/health")
    assert response.status_code == 200


def test_missing_bearer_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    with _build_client(monkeypatch) as client:
        response = client.post("/chat/completions", json={"messages": []})
    assert response.status_code == 401


def test_invalid_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SATokenAuthMiddleware, "_validate_token", lambda *_: None)
    with _build_client(monkeypatch) as client:
        response = client.post(
            "/chat/completions",
            json={"messages": []},
            headers={"Authorization": "Bearer invalid"},
        )
    assert response.status_code == 401


def test_allowlisted_serviceaccount_returns_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SATokenAuthMiddleware,
        "_validate_token",
        lambda *_: _review("system:serviceaccount:ci-testing:allowed-caller"),
    )
    with _build_client(monkeypatch) as client:
        response = client.post(
            "/chat/completions",
            json={"messages": []},
            headers={"Authorization": "Bearer good-token"},
        )
    assert response.status_code == 200


def test_non_allowlisted_serviceaccount_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SATokenAuthMiddleware,
        "_validate_token",
        lambda *_: _review("system:serviceaccount:ci-testing:blocked-caller"),
    )
    with _build_client(monkeypatch) as client:
        response = client.post(
            "/chat/completions",
            json={"messages": []},
            headers={"Authorization": "Bearer good-token"},
        )
    assert response.status_code == 403


def test_tokenreview_failure_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_):
        raise RuntimeError("token review unavailable")

    monkeypatch.setattr(SATokenAuthMiddleware, "_validate_token", _raise)
    with _build_client(monkeypatch) as client:
        response = client.post(
            "/chat/completions",
            json={"messages": []},
            headers={"Authorization": "Bearer good-token"},
        )
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("username", "expected"),
    [
        (
            "system:serviceaccount:ci-testing:allowed-caller",
            "ci-testing:allowed-caller",
        ),
        ("system:serviceaccount:ci-testing:", None),
        ("system:serviceaccount::allowed-caller", None),
        ("system:serviceaccount:ci-testing:allowed:extra", None),
        ("system:user:ci-testing:allowed-caller", None),
    ],
)
def test_caller_identity_edge_cases(username: str, expected: str | None) -> None:
    assert SATokenAuthMiddleware._caller_identity(username) == expected


def test_auth_enabled_requires_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("AUTH_AUDIENCE", raising=False)
    monkeypatch.setenv("AUTH_ALLOWED_SERVICEACCOUNTS", "ci-testing:allowed-caller")

    app = Starlette(
        routes=[
            Route("/health", _health),
            Route("/chat/completions", _chat, methods=["POST"]),
        ]
    )
    app.add_middleware(SATokenAuthMiddleware)

    with pytest.raises(
        RuntimeError, match="AUTH_ENABLED=true requires AUTH_AUDIENCE to be set"
    ):
        with TestClient(app):
            pass
