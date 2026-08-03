"""Thin auth layer that wraps main:app without modifying agent code.

Authenticates requests using K8s ServiceAccount tokens via TokenReview API.
Set ``K8S_API_URL`` and ``K8S_REVIEWER_TOKEN`` to enable auth.
When not configured, every request passes through unchanged.

Usage:
    K8S_API_URL=https://... K8S_REVIEWER_TOKEN=... uvicorn auth_wrapper:app --host 0.0.0.0 --port 8080
"""

import logging
from os import getenv

import httpx
from main import app  # noqa: F401 — re-exported for uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger("auth_wrapper")

_K8S_API_URL = getenv("K8S_API_URL", "").strip().rstrip("/")
_K8S_REVIEWER_TOKEN = getenv("K8S_REVIEWER_TOKEN", "").strip()
_PROTECTED_PATHS = frozenset({"/chat/completions", "/chat/completions/"})

_AUTH_ENABLED = bool(_K8S_API_URL and _K8S_REVIEWER_TOKEN)


def _validate_k8s_token(token: str) -> bool:
    if not (_K8S_API_URL and _K8S_REVIEWER_TOKEN):
        return False
    try:
        resp = httpx.post(
            f"{_K8S_API_URL}/apis/authentication.k8s.io/v1/tokenreviews",
            json={
                "apiVersion": "authentication.k8s.io/v1",
                "kind": "TokenReview",
                "spec": {"token": token},
            },
            headers={
                "Authorization": f"Bearer {_K8S_REVIEWER_TOKEN}",
                "Content-Type": "application/json",
            },
            verify=False,
            timeout=10,
        )
        if resp.status_code == 201:
            status = resp.json().get("status", {})
            if status.get("authenticated"):
                user = status.get("user", {}).get("username", "unknown")
                log.info("K8s token authenticated: %s", user)
                return True
        return False
    except Exception:
        log.exception("K8s TokenReview failed")
        return False


class _BearerAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        if request.url.path not in _PROTECTED_PATHS:
            await self.app(scope, receive, send)
            return

        token = ""
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
        else:
            token = request.headers.get("x-api-key", "")

        if not token:
            response = JSONResponse(
                {
                    "error": "Missing API key (use X-Api-Key or Authorization: Bearer header)"
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        if _validate_k8s_token(token):
            await self.app(scope, receive, send)
            return

        response = JSONResponse({"error": "Invalid API key"}, status_code=401)
        await response(scope, receive, send)


if _AUTH_ENABLED:
    app.add_middleware(_BearerAuthMiddleware)
