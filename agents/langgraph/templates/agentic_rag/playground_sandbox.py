"""
OpenShell sandbox playground integration.

Provides routes for the embedded playground UI when running in sandbox mode.
This module is imported conditionally when K8S_REVIEWER_TOKEN is set.
"""

import json
import logging
from os import getenv
from pathlib import Path

import requests as http_requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)

_BASE_DIR = Path(__file__).resolve().parent
_PLAYGROUND_HTML = _BASE_DIR / "playground" / "templates" / "index.html"
_SANDBOX_PLAYGROUND_HTML = _BASE_DIR / "playground-sandbox" / "templates" / "index.html"
_IMAGES_DIR = _BASE_DIR / "images"
if not _IMAGES_DIR.is_dir():
    _IMAGES_DIR = _BASE_DIR.parent.parent.parent / "images"

_PLAYGROUND_URL = getenv("PLAYGROUND_URL", "http://localhost:5002").rstrip("/")
_SANDBOX_MODE = bool(getenv("K8S_REVIEWER_TOKEN", "").strip())
_PLAYGROUND_TOKEN = getenv("PLAYGROUND_TOKEN", "").strip()


class ChatMessage(BaseModel):
    """A message in the conversation."""

    role: str = Field(
        ...,
        description="The role of the message author.",
        examples=["user", "assistant", "system", "tool"],
    )
    content: str = Field(
        ...,
        description="The contents of the message.",
        examples=["What is LangChain?"],
    )


class ChatCompletionRequest(BaseModel):
    """Creates a model response for the given chat conversation."""

    messages: list[ChatMessage] = Field(
        ...,
        min_length=1,
        description="A list of messages comprising the conversation so far.",
    )
    model: str | None = Field(
        None,
        description="ID of the model to use. Defaults to the server's configured MODEL_ID.",
    )
    stream: bool = Field(
        False,
        description="If true, partial message deltas will be sent as SSE `data: {json}\\n\\n` events, terminated by `data: [DONE]\\n\\n`.",
    )


def _auth_enabled() -> bool:
    return getenv("AUTH_ENABLED", "false").strip().lower() == "true"


def _playground_page_response() -> FileResponse:
    """Return the playground page."""
    return FileResponse(_SANDBOX_PLAYGROUND_HTML)


@router.get("/docs", response_class=HTMLResponse)
async def custom_swagger_ui(request: Request):
    """Serve Swagger UI with a shortcut to the sandbox playground."""
    # Access app from request to avoid circular import
    swagger_html = get_swagger_ui_html(
        openapi_url=request.app.openapi_url,
        title=f"{request.app.title} - Swagger UI",
        swagger_favicon_url="https://fastapi.tiangolo.com/img/favicon.png",
    )
    html = swagger_html.body.decode("utf-8")
    shortcut = (
        '<a href="/playground" class="sandbox-playground-link" '
        'title="Open Sandbox Playground">🎮 Sandbox Playground</a>'
    )
    styles = """
    <style>
      .sandbox-playground-link {
        position: fixed;
        top: 18px;
        right: 24px;
        z-index: 10;
        padding: 8px 12px;
        border-radius: 4px;
        color: #fff;
        background: #3b4151;
        font: 600 13px sans-serif;
        text-decoration: none;
      }
      .sandbox-playground-link:hover { background: #2f3545; }
    </style>
    """
    html = html.replace("<body>", f"<body>{styles}{shortcut}", 1)
    return HTMLResponse(html)


@router.get(
    "/playground",
    summary="Open the sandbox playground",
    description=(
        "Redirects to the local sandbox playground UI. Start it with "
        "`make playground-sandbox`; it obtains the ServiceAccount token "
        "automatically through `oc`."
    ),
    responses={307: {"description": "Redirect to the sandbox playground UI"}},
)
async def playground_redirect():
    """Serve the sandbox playground or redirect to the local fallback UI."""
    if _SANDBOX_MODE:
        # The token is required by /api/chat and expires after a short period.
        return _playground_page_response()
    return RedirectResponse(url=_PLAYGROUND_URL)


@router.get("/", response_class=HTMLResponse)
async def playground():
    """Serve the playground chat UI."""
    if _SANDBOX_MODE:
        return _playground_page_response()
    if _auth_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(_PLAYGROUND_HTML)


@router.get("/api/health")
async def playground_health(request: Request):
    """Expose the agent health response expected by the sandbox UI."""
    # Access agent_graph from app.state to avoid circular import
    initialized = getattr(request.app.state, "agent_graph", None) is not None
    body = {
        "status": "healthy" if initialized else "not_ready",
        "agent_initialized": initialized,
    }
    if not initialized:
        return JSONResponse(status_code=503, content=body)
    return body


@router.post("/api/chat")
async def playground_chat(chat_request: ChatCompletionRequest, request: Request):
    """Proxy sandbox UI requests with the server-side ServiceAccount token.

    Security: ``auth_wrapper.py`` authenticates the caller with a Kubernetes
    ServiceAccount token before this route is reached.
    """
    if not (_SANDBOX_MODE and _PLAYGROUND_TOKEN):
        raise HTTPException(
            status_code=503, detail="Sandbox playground is not configured"
        )

    payload = chat_request.model_dump(exclude_none=True)
    payload["stream"] = True

    def event_generator():
        try:
            with http_requests.post(
                "http://127.0.0.1:8080/chat/completions",
                json=payload,
                headers={"X-Api-Key": _PLAYGROUND_TOKEN},
                stream=True,
                timeout=(10, 300),
            ) as response:
                if response.status_code != 200:
                    error = json.dumps(
                        {
                            "error": {
                                "message": f"Agent returned {response.status_code}: {response.text[:500]}"
                            }
                        }
                    )
                    yield f"data: {error}\n\n"
                    return
                for chunk in response.iter_content(
                    chunk_size=None, decode_unicode=True
                ):
                    if chunk:
                        yield chunk
        except http_requests.RequestException as exc:
            logger.exception("Sandbox playground proxy request failed")
            error = json.dumps({"error": {"message": str(exc)}})
            yield f"data: {error}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/images/{filename:path}")
async def serve_image(filename: str):
    """Serve images from the project-level images directory."""
    if _auth_enabled():
        raise HTTPException(status_code=404, detail="Not found")

    # Prevent path traversal (CWE-22): instead of constructing a path from
    # user input, enumerate the allowed directory and match by name.
    from pathlib import PurePosixPath

    requested_name = PurePosixPath(filename).name
    if not requested_name or requested_name in (".", ".."):
        raise HTTPException(status_code=404, detail="Image not found")

    for entry in _IMAGES_DIR.resolve().iterdir():
        if entry.is_file() and entry.name == requested_name:
            return FileResponse(entry)

    raise HTTPException(status_code=404, detail="Image not found")
