"""Security regression tests for the sandbox playground proxy."""

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auth_wrapper import _BearerAuthMiddleware  # noqa: E402


def test_playground_page_cookie_does_not_authenticate_api_chat(monkeypatch):
    """A public playground page cannot use the server-side token proxy anonymously."""
    import auth_wrapper
    import playground_sandbox

    monkeypatch.setattr(playground_sandbox, "_SANDBOX_MODE", True)
    monkeypatch.setattr(playground_sandbox, "_PLAYGROUND_TOKEN", "server-token")

    async def reject_all_tokens(_token: str) -> bool:
        return False

    monkeypatch.setattr(auth_wrapper, "_validate_k8s_token", reject_all_tokens)
    app = FastAPI()
    app.include_router(playground_sandbox.router)
    client = TestClient(_BearerAuthMiddleware(app))

    page = client.get("/playground")
    assert page.status_code == 200

    response = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 401
