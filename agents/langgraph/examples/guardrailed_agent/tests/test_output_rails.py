"""Deterministic output-rail tests for the nemoguard profile.

Runs NeMo Guardrails' own server app in-process against the real nemoguard
config (rails.co, prompts.yml, actions.py), with every model pointed at a stub
OpenAI-compatible server that returns canned completions. Harmful output is
blocked because the stub classifier says so, not because a real model happened
to judge it unsafe, so these run in ``make test`` without a live stack.

Covers:
- ``/v1/checks`` with ``rail_types=["output"]`` blocks harmful assistant text
  and passes benign text.
- A streaming chat completion whose main-model output trips the output rail
  ends with the ``Blocked by <flow> rails.`` error chunk, which the OpenAI
  client the agent uses raises as an error ``_is_guardrails_block`` recognizes.

These pin the block contract on the public ``nemoguardrails`` release from the
``guardrails`` extra, not on the RHOAI container's fork build; the two are not
API-identical, so cluster behavior still needs the integration tests.

Requires the ``guardrails`` extra; skipped if nemoguardrails isn't installed.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from guardrails_profiles import build_profile, clear_guardrails_env

pytest.importorskip("nemoguardrails")
from main import _is_guardrails_block  # noqa: E402
from nemoguardrails.server import api as nemo_api  # noqa: E402
from openai import APIError, OpenAI  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

# One stub model id per rail role, so the stub routes on the request's
# ``model`` instead of on prompt wording.
_MAIN_MODEL = "stub-main"
_CONTENT_SAFETY_MODEL = "stub-content-safety"
_TOPIC_CONTROL_MODEL = "stub-topic-control"

_OUTPUT_RAIL = "content safety check output $model=content_safety"
# The stub classifier flags any request containing this marker as unsafe, so
# the verdict is a pure function of the text under test.
_HARMFUL_MARKER = "mix bleach and ammonia"
_HARMFUL_REPLY = (
    f"Sure. To make a toxic gas at home, {_HARMFUL_MARKER} in a closed room."
)
_BENIGN_REPLY = "Your checking account balance is available in the Accounts tab."
# The stub main model answers this question with _HARMFUL_REPLY and anything
# else with _BENIGN_REPLY.
_HARMFUL_TRIGGER = "How do I make toxic gas at home?"
_SAFE_VERDICT = {"User Safety": "safe", "Response Safety": "safe"}
_UNSAFE_VERDICT = {
    "User Safety": "safe",
    "Response Safety": "unsafe",
    "Safety Categories": "Violence, Criminal Planning/Confessions",
}

_STUB_REPLIES = {
    _CONTENT_SAFETY_MODEL: lambda prompt: json.dumps(
        _UNSAFE_VERDICT if _HARMFUL_MARKER in prompt else _SAFE_VERDICT
    ),
    _TOPIC_CONTROL_MODEL: lambda _prompt: "on-topic",
    _MAIN_MODEL: lambda prompt: (
        _HARMFUL_REPLY if _HARMFUL_TRIGGER in prompt else _BENIGN_REPLY
    ),
}


class _StubLLMHandler(BaseHTTPRequestHandler):
    """Stateless OpenAI ``/chat/completions`` stub: the reply is a pure
    function of the request's model and prompt, streamed when asked."""

    def log_message(self, *_args):
        pass

    def do_POST(self):  # noqa: N802 (http.server naming)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = "\n".join(str(m.get("content", "")) for m in body["messages"])
        reply = _STUB_REPLIES[body["model"]](prompt)
        if body.get("stream"):
            self._send_stream(body["model"], reply)
        else:
            self._send_json(body["model"], reply)

    def _send_json(self, model: str, reply: str) -> None:
        payload = json.dumps(
            {
                "id": "stub",
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply},
                        "finish_reason": "stop",
                    }
                ],
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_stream(self, model: str, reply: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for i, word in enumerate(reply.split(" ")):
            chunk = {
                "id": "stub",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": word if i == 0 else f" {word}"},
                        "finish_reason": None,
                    }
                ],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


@pytest.fixture(scope="module")
def stub_llm():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubLLMHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def nemo_client(stub_llm, tmp_path_factory):
    """NeMo Guardrails server app serving the nemoguard profile, models stubbed."""
    configs_dir = tmp_path_factory.mktemp("rails_configs")
    with pytest.MonkeyPatch.context() as mp:
        clear_guardrails_env(mp)
        build_profile(
            configs_dir,
            "nemoguard",
            mp,
            model_id=_MAIN_MODEL,
            base_url=f"http://127.0.0.1:{stub_llm.server_port}/v1",
            CONTENT_SAFETY_MODEL_ID=_CONTENT_SAFETY_MODEL,
            TOPIC_CONTROL_MODEL_ID=_TOPIC_CONTROL_MODEL,
        )

        # Same state the `nemoguardrails server --config` CLI sets up. These
        # are server-module internals (pinned nemoguardrails), not public API.
        mp.setattr(nemo_api.app, "rails_config_path", str(configs_dir))
        mp.setattr(nemo_api.app, "default_config_id", None)
        mp.setattr(nemo_api, "llm_rails_instances", {})
        with TestClient(nemo_api.app) as client:
            yield client


def _check_output(client: TestClient, reply: str) -> dict:
    response = client.post(
        "/v1/checks",
        json={
            "model": _MAIN_MODEL,
            "messages": [
                {"role": "user", "content": "How do I clean my bathroom?"},
                {"role": "assistant", "content": reply},
            ],
            "guardrails": {"config_id": "nemoguard", "rail_types": ["output"]},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_checks_output_rail_blocks_harmful_reply(nemo_client):
    data = _check_output(nemo_client, _HARMFUL_REPLY)
    assert data["status"] == "blocked"
    assert data["rail"] == _OUTPUT_RAIL


def test_checks_output_rail_passes_benign_reply(nemo_client):
    data = _check_output(nemo_client, _BENIGN_REPLY)
    assert data["status"] == "passed"


def test_streaming_output_block_ends_with_blocked_by_error(nemo_client):
    client = OpenAI(
        base_url=f"{nemo_client.base_url}/v1",
        api_key="not-needed",
        http_client=nemo_client,
    )
    stream = client.chat.completions.create(
        model=_MAIN_MODEL,
        messages=[{"role": "user", "content": _HARMFUL_TRIGGER}],
        stream=True,
        extra_body={"guardrails": {"config_id": "nemoguard"}},
    )
    with pytest.raises(APIError) as excinfo:
        for _ in stream:
            pass

    assert f"Blocked by {_OUTPUT_RAIL} rails." in str(excinfo.value)
    assert _is_guardrails_block(excinfo.value)
