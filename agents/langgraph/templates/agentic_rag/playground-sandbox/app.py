"""
Playground UI for the LangGraph Agentic RAG Agent running in openShell sandbox.

A Flask chat interface that proxies requests to the sandbox agent's
/chat/completions endpoint with K8s SA token authentication and streaming support.

Usage:
    # Start the playground (auto-fetches agent URL and SA token from OpenShift):
    cd agents/langgraph/templates/agentic_rag
    python playground-sandbox/app.py

    # Or manually specify:
    AGENT_URL=https://rag-sandbox--agent.openshell.apps.example.com \
    AGENT_TOKEN=$(oc get secret agent-client-token -o jsonpath='{.data.token}' | base64 -d) \
    AGENT_CA_BUNDLE=/path/to/ca.crt \  # optional: enable TLS verification
    flask --app playground-sandbox/app run --port 5002

The app will:
1. Auto-detect AGENT_URL from the openshell Route (if not set)
2. Auto-fetch AGENT_TOKEN from the agent-client-token Secret (if not set)
3. Inject X-Api-Key header on all /chat/completions requests
"""

import json
import logging
import subprocess
from os import getenv
from pathlib import Path

import requests as http_requests
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
    stream_with_context,
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

IMAGES_DIR = Path(__file__).resolve().parents[5] / "images"

app = Flask(__name__)


def get_current_namespace():
    """Get current OpenShift namespace/project."""
    try:
        result = subprocess.run(
            ["oc", "project", "-q"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_agent_url():
    """Auto-detect agent URL from OpenShift Route."""
    url = getenv("AGENT_URL")
    if url:
        return url

    try:
        # Route is in openshell namespace
        result = subprocess.run(
            [
                "oc",
                "get",
                "route",
                "openshell-rag-agent",
                "-n",
                "openshell",
                "-o",
                "jsonpath={.spec.host}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            host = result.stdout.strip()
            logger.info(f"Auto-detected agent URL from route: https://{host}")
            return f"https://{host}"
    except Exception:
        logger.exception("Failed to auto-detect agent URL from route")

    logger.warning("AGENT_URL not set and route detection failed, using fallback")
    return "http://localhost:8000"


def get_agent_token():
    """Auto-fetch agent token from OpenShift Secret in current namespace."""
    token = getenv("AGENT_TOKEN")
    if token:
        return token

    namespace = get_current_namespace()
    if not namespace:
        logger.warning("Could not determine current namespace")
        return None

    try:
        result = subprocess.run(
            [
                "oc",
                "get",
                "secret",
                "agent-client-token",
                "-n",
                namespace,
                "-o",
                "jsonpath={.data.token}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            import base64

            token_b64 = result.stdout.strip()
            token = base64.b64decode(token_b64).decode("utf-8")
            logger.info(
                f"Auto-fetched agent token from Secret agent-client-token in namespace {namespace}"
            )
            return token
    except Exception:
        logger.exception("Failed to auto-fetch agent token from Secret")

    logger.warning(
        f"AGENT_TOKEN not set and Secret fetch failed (namespace: {namespace})"
    )
    return None


CURRENT_NAMESPACE = get_current_namespace()
AGENT_URL = get_agent_url()
AGENT_TOKEN = get_agent_token()
AGENT_CA_BUNDLE = getenv("AGENT_CA_BUNDLE", "")
if AGENT_CA_BUNDLE and Path(AGENT_CA_BUNDLE).is_file():
    VERIFY_TLS = AGENT_CA_BUNDLE
else:
    VERIFY_TLS = False
    if AGENT_CA_BUNDLE:
        logger.warning(
            "AGENT_CA_BUNDLE=%s not found, TLS verification disabled", AGENT_CA_BUNDLE
        )
    else:
        logger.warning(
            "AGENT_CA_BUNDLE not set, TLS verification disabled (set to a CA path to enable)"
        )

logger.info(f"Current namespace: {CURRENT_NAMESPACE or 'UNKNOWN'}")
logger.info(f"Agent URL: {AGENT_URL}")
logger.info(f"Agent token: {'***' + AGENT_TOKEN[-8:] if AGENT_TOKEN else 'NOT SET'}")
logger.info(f"TLS verify: {VERIFY_TLS}")


@app.route("/images/<path:filename>")
def serve_image(filename):
    """Serve images from the project-level images directory."""
    return send_from_directory(IMAGES_DIR, filename)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def health():
    """Check if the agent is reachable (health endpoint does not require auth)."""
    try:
        resp = http_requests.get(f"{AGENT_URL}/health", timeout=10, verify=VERIFY_TLS)
        return jsonify(resp.json()), resp.status_code
    except Exception:
        logger.exception("Error checking agent health")
        return (
            jsonify(
                {
                    "status": "unreachable",
                    "error": "Agent is unreachable. Please try again later.",
                }
            ),
            503,
        )


@app.route("/api/chat", methods=["POST"])
def chat():
    """Proxy chat requests to the agent with K8s SA token auth and streaming."""
    if not AGENT_TOKEN:
        return (
            jsonify(
                {
                    "error": {
                        "message": "Agent token not configured. Set AGENT_TOKEN or ensure agent-client-token Secret exists."
                    }
                }
            ),
            500,
        )

    data = request.get_json() or {}
    messages = data.get("messages", [])

    payload = {
        "messages": messages,
        "stream": True,
    }

    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": AGENT_TOKEN,
    }

    logger.info(
        f"Sending request to {AGENT_URL}/chat/completions (messages={len(payload.get('messages', []))}, stream={payload.get('stream')})"
    )

    def generate():
        try:
            with http_requests.post(
                f"{AGENT_URL}/chat/completions",
                json=payload,
                headers=headers,
                stream=True,
                timeout=(10, 300),
                verify=VERIFY_TLS,
            ) as resp:
                logger.info(f"Agent response status: {resp.status_code}")

                if resp.status_code != 200:
                    error_msg = resp.text[:500]
                    logger.error(f"Agent error: {error_msg}")
                    error = json.dumps(
                        {
                            "error": {
                                "message": f"Agent returned {resp.status_code}: {error_msg}"
                            }
                        }
                    )
                    yield f"data: {error}\n\n"
                    return

                for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
                    if chunk:
                        logger.debug(f"Chunk: {chunk[:200]}")
                        yield chunk

        except http_requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to agent at {AGENT_URL}")
            error = json.dumps(
                {
                    "error": {
                        "message": f"Cannot connect to agent at {AGENT_URL}. Is it running?"
                    }
                }
            )
            yield f"data: {error}\n\n"
        except http_requests.exceptions.ReadTimeout:
            logger.error("Agent request timed out")
            error = json.dumps({"error": {"message": "Agent request timed out (300s)"}})
            yield f"data: {error}\n\n"
        except Exception:
            logger.exception("Unexpected error in proxy")
            error = json.dumps({"error": {"message": "Internal server error"}})
            yield f"data: {error}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


if __name__ == "__main__":
    if not AGENT_TOKEN:
        logger.error(
            f"AGENT_TOKEN not found. Set it manually or ensure:\n"
            f"  1. You're logged into OpenShift (oc whoami)\n"
            f"  2. You're in the correct namespace (current: {CURRENT_NAMESPACE or 'UNKNOWN'})\n"
            f"  3. Secret 'agent-client-token' exists in your namespace (oc get secret agent-client-token)\n"
            f"  4. If missing, run: make start-agent"
        )
        exit(1)

    debug_mode = getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, host=getenv("FLASK_HOST", "127.0.0.1"), port=5002)
