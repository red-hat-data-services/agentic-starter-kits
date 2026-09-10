"""Security regression tests for the sandbox playground proxy."""

import sys
from pathlib import Path

from fastapi import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playground_sandbox import (  # noqa: E402
    _PLAYGROUND_CSRF_COOKIE,
    _PLAYGROUND_CSRF_HEADER,
    _playground_request_is_authorized,
)


def _request(
    *, cookies: dict[str, str] | None = None, headers: dict[str, str] | None = None
) -> Request:
    cookie_header = "; ".join(
        f"{key}={value}" for key, value in (cookies or {}).items()
    )
    raw_headers = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    if cookie_header:
        raw_headers.append((b"cookie", cookie_header.encode()))
    return Request(
        {"type": "http", "headers": raw_headers, "method": "POST", "path": "/api/chat"}
    )


def test_playground_proxy_rejects_request_without_csrf_token():
    assert not _playground_request_is_authorized(_request())


def test_playground_proxy_rejects_mismatched_csrf_tokens():
    assert not _playground_request_is_authorized(
        _request(
            cookies={_PLAYGROUND_CSRF_COOKIE: "cookie-token"},
            headers={_PLAYGROUND_CSRF_HEADER: "different-token"},
        )
    )


def test_playground_proxy_accepts_matching_csrf_tokens():
    token = "issued-playground-token"
    assert _playground_request_is_authorized(
        _request(
            cookies={_PLAYGROUND_CSRF_COOKIE: token},
            headers={_PLAYGROUND_CSRF_HEADER: token},
        )
    )
