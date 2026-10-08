"""Thin auth layer that wraps main:app without modifying agent code.

Authenticates requests using K8s ServiceAccount tokens via TokenReview API.
Set ``K8S_API_URL`` and ``K8S_REVIEWER_TOKEN`` to enable auth.
When not configured, every request passes through unchanged.

Usage:
    K8S_API_URL=https://... K8S_REVIEWER_TOKEN=... uvicorn auth_wrapper:app --host 0.0.0.0 --port 8080
"""

import logging
from os import getenv
from pathlib import Path

import httpx
from main import app  # noqa: F401 — re-exported for uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger("auth_wrapper")

_K8S_API_URL = getenv("K8S_API_URL", "").strip().rstrip("/")
_K8S_REVIEWER_TOKEN = getenv("K8S_REVIEWER_TOKEN", "").strip()
_ALLOWED_SA_USERNAME = getenv("ALLOWED_SA_USERNAME", "").strip()
_K8S_CA_PATH = getenv(
    "K8S_CA_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
)
_K8S_API_INSECURE = getenv("K8S_API_INSECURE", "").strip().lower() == "true"
# The playground proxy must not be usable as an unauthenticated way to spend
# the server-side PLAYGROUND_TOKEN. Kubernetes token authentication is the
# actual caller authentication for both direct chat and proxied chat requests.
_PROTECTED_PATHS = frozenset(
    {
        "/chat/completions",
        "/chat/completions/",
        "/api/chat",
        "/api/chat/",
    }
)

_AUTH_ENABLED = bool(_K8S_API_URL and _K8S_REVIEWER_TOKEN)

# Determine TLS verification strategy - FAIL CLOSED by default
_ca_path_exists = Path(_K8S_CA_PATH).is_file()
if _ca_path_exists:
    # Use the K8s CA certificate if available
    _tls_verify: str | bool = _K8S_CA_PATH
elif _K8S_API_INSECURE:
    # Explicit opt-in to insecure mode (e.g., OpenShell sandbox)
    # This is intentionally verbose to make the security implications clear
    if _AUTH_ENABLED:
        log.warning(
            "K8S_API_INSECURE=true: Using insecure TLS verification (verify=False). "
            "This is ONLY acceptable in isolated test environments like OpenShell sandbox. "
            "NEVER use this in production."
        )
    _tls_verify: str | bool = False
else:
    # FAIL CLOSED: CA certificate not found and no explicit insecure opt-in
    if _AUTH_ENABLED:
        raise RuntimeError(
            f"K8s CA certificate not found at {_K8S_CA_PATH} and K8S_API_INSECURE is not set. "
            "Either provide a valid CA certificate via K8S_CA_PATH, "
            "or set K8S_API_INSECURE=true for test environments (NOT production)."
        )
    # Auth not enabled, doesn't matter
    _tls_verify: str | bool = True


# Cached HTTP client for connection reuse across token-review calls
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Get or create the cached HTTP client for K8s TokenReview calls."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(verify=_tls_verify, timeout=10.0)
    return _http_client


async def _validate_k8s_token(token: str) -> bool:
    if not (_K8S_API_URL and _K8S_REVIEWER_TOKEN):
        return False
    try:
        client = _get_http_client()
        resp = await client.post(
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
        )
        if resp.status_code == 201:
            status = resp.json().get("status", {})
            if status.get("authenticated"):
                user = status.get("user", {}).get("username", "unknown")
                if _ALLOWED_SA_USERNAME and user != _ALLOWED_SA_USERNAME:
                    log.warning(
                        "K8s token authenticated but username mismatch: got %s, expected %s",
                        user,
                        _ALLOWED_SA_USERNAME,
                    )
                    return False
                log.info("K8s token authenticated: %s", user)
                return True
        return False
    except Exception as e:
        log.exception("K8s TokenReview failed: %s", str(e))
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
                {"error": "Missing API key (use X-Api-Key)"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        if await _validate_k8s_token(token):
            await self.app(scope, receive, send)
            return

        response = JSONResponse({"error": "Invalid API key"}, status_code=401)
        await response(scope, receive, send)


if _AUTH_ENABLED:
    app.add_middleware(_BearerAuthMiddleware)
