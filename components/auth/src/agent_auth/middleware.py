from __future__ import annotations

import json
import logging
import os
from typing import Any

from kubernetes import client, config
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


class SATokenAuthMiddleware:
    """ASGI middleware that authenticates/authorizes ServiceAccount tokens."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.enabled = os.getenv("AUTH_ENABLED", "false").strip().lower() == "true"
        self.audience = os.getenv("AUTH_AUDIENCE", "").strip()
        self.exclude_paths = {
            path.strip()
            for path in os.getenv("AUTH_EXCLUDE_PATHS", "/health").split(",")
            if path.strip()
        }
        self.allowed_serviceaccounts = {
            value.strip()
            for value in os.getenv("AUTH_ALLOWED_SERVICEACCOUNTS", "").split(",")
            if value.strip()
        }
        if self.enabled and not self.audience:
            raise RuntimeError("AUTH_ENABLED=true requires AUTH_AUDIENCE to be set")
        if self.enabled and not self.allowed_serviceaccounts:
            logger.warning(
                "AUTH_ENABLED=true but AUTH_ALLOWED_SERVICEACCOUNTS is empty; "
                "all non-excluded requests will be denied"
            )
        self._auth_api: client.AuthenticationV1Api | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.exclude_paths:
            await self.app(scope, receive, send)
            return

        token = self._extract_token(scope)
        if token is None:
            await self._send_401(send, "Missing Bearer token")
            return

        try:
            review = self._validate_token(token)
        except Exception:
            logger.exception("TokenReview API request failed")
            await self._send_503(send, "Authentication service unavailable")
            return

        if review is None:
            await self._send_401(send, "Invalid or expired token")
            return

        username = getattr(getattr(review.status, "user", None), "username", "")
        caller_identity = self._caller_identity(username)
        if (
            caller_identity is None
            or caller_identity not in self.allowed_serviceaccounts
        ):
            await self._send_403(send, "Caller is not allowed")
            return

        await self.app(scope, receive, send)

    def _extract_token(self, scope: Scope) -> str | None:
        for raw_key, raw_value in scope.get("headers", []):
            if raw_key.lower() != b"authorization":
                continue
            value = raw_value.decode("latin-1").strip()
            if not value:
                return None
            token_type, _, token = value.partition(" ")
            if token_type.lower() != "bearer" or not token.strip():
                return None
            return token.strip()
        return None

    def _get_auth_api(self) -> client.AuthenticationV1Api:
        if self._auth_api is None:
            config.load_incluster_config()
            self._auth_api = client.AuthenticationV1Api()
        return self._auth_api

    def _validate_token(self, token: str) -> Any | None:
        review = self._get_auth_api().create_token_review(
            client.V1TokenReview(
                spec=client.V1TokenReviewSpec(token=token, audiences=[self.audience])
            )
        )
        if not getattr(review.status, "authenticated", False):
            return None
        token_audiences = getattr(review.status, "audiences", None) or []
        if self.audience not in token_audiences:
            logger.warning("TokenReview returned no matching audience")
            return None
        return review

    @staticmethod
    def _caller_identity(username: str) -> str | None:
        prefix = "system:serviceaccount:"
        if not username.startswith(prefix):
            return None
        remainder = username.removeprefix(prefix)
        namespace, sep, serviceaccount = remainder.partition(":")
        if not sep or not namespace or not serviceaccount:
            return None
        if ":" in namespace or ":" in serviceaccount:
            return None
        return f"{namespace}:{serviceaccount}"

    async def _send_401(self, send: Send, message: str) -> None:
        await self._send_json(send, 401, {"detail": message})

    async def _send_403(self, send: Send, message: str) -> None:
        await self._send_json(send, 403, {"detail": message})

    async def _send_503(self, send: Send, message: str) -> None:
        await self._send_json(send, 503, {"detail": message})

    async def _send_json(
        self, send: Send, status: int, payload: dict[str, str]
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        headers = [(b"content-type", b"application/json")]
        await send(
            {"type": "http.response.start", "status": status, "headers": headers}
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})
