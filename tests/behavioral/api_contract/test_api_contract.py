"""API contract tests for agentic-starter-kits agents.

Tests the FastAPI application layer that all agents share:
endpoint schemas, response formats, error handling, and streaming.
These test the repo code, not the model.

All agents in agentic-starter-kits implement:
  POST /chat/completions  (OpenAI-compatible)
  GET  /health
  GET  /                   (playground HTML)
"""

from __future__ import annotations

import json
from typing import Any

import pytest

pytestmark = pytest.mark.api_contract


class TestHealthEndpoint:
    """GET /health must conform to HealthResponse schema."""

    async def test_health_returns_expected_fields(self, agent_url, http_client):
        """Health response must contain 'status' (str) and 'agent_initialized' (bool).

        This tests the HealthResponse Pydantic model and the lifespan
        initialization in main.py.
        """
        resp = await http_client.get(f"{agent_url}/health", timeout=10.0)

        assert resp.status_code == 200, (
            f"Health endpoint returned {resp.status_code}: {resp.text}"
        )

        data = resp.json()
        assert "status" in data, f"Missing 'status' field. Got: {data}"
        assert "agent_initialized" in data, f"Missing 'agent_initialized' field. Got: {data}"
        assert isinstance(data["status"], str), (
            f"'status' should be str, got {type(data['status'])}"
        )
        assert isinstance(data["agent_initialized"], bool), (
            f"'agent_initialized' should be bool, got {type(data['agent_initialized'])}"
        )


class TestChatCompletionSchema:
    """POST /chat/completions must return OpenAI-compatible response schema."""

    async def test_non_streaming_response_schema(self, agent_url, http_client):
        """Non-streaming response must match ChatCompletionResponse model.

        Required fields: id (str), object ("chat.completion"), created (int),
        model (str), choices (list with message.role + message.content).
        Tests the Pydantic response model and the ainvoke/kickoff code path.
        """
        payload = {
            "messages": [{"role": "user", "content": "What is OpenShift?"}],
            "stream": False,
        }

        resp = await http_client.post(
            f"{agent_url}/chat/completions", json=payload, timeout=60.0
        )

        assert resp.status_code == 200, (
            f"Chat endpoint returned {resp.status_code}: {resp.text}"
        )

        data = resp.json()

        # Top-level fields
        assert isinstance(data.get("id"), str), f"'id' should be str. Got: {data.get('id')}"
        assert data.get("object") == "chat.completion", (
            f"'object' should be 'chat.completion'. Got: {data.get('object')}"
        )
        assert isinstance(data.get("created"), int), (
            f"'created' should be int. Got: {data.get('created')}"
        )
        assert isinstance(data.get("model"), str), (
            f"'model' should be str. Got: {data.get('model')}"
        )

        # Choices
        choices = data.get("choices")
        assert isinstance(choices, list) and len(choices) > 0, (
            f"'choices' should be non-empty list. Got: {choices}"
        )

        choice = choices[0]
        assert "message" in choice, f"Choice missing 'message'. Got: {choice}"
        assert choice["message"].get("role") == "assistant", (
            f"Message role should be 'assistant'. Got: {choice['message'].get('role')}"
        )
        assert isinstance(choice["message"].get("content"), str), (
            f"Message content should be str. Got: {type(choice['message'].get('content'))}"
        )
        assert "finish_reason" in choice, f"Choice missing 'finish_reason'. Got: {choice}"


class TestStreamingContract:
    """POST /chat/completions with stream=true must return valid SSE."""

    async def test_streaming_returns_sse_with_done(self, agent_url, http_client):
        """Streaming response must be SSE format ending with data: [DONE].

        Tests the event_generator() code path in main.py — the SSE framing,
        chunk JSON structure, and stream termination.
        """
        payload = {
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }

        chunks: list[dict[str, Any]] = []
        saw_done = False

        async with http_client.stream(
            "POST", f"{agent_url}/chat/completions", json=payload, timeout=60.0
        ) as resp:
            assert resp.status_code == 200, (
                f"Streaming endpoint returned {resp.status_code}"
            )

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    saw_done = True
                    break
                try:
                    chunk = json.loads(data_str)
                    chunks.append(chunk)
                except json.JSONDecodeError:
                    pytest.fail(f"SSE chunk is not valid JSON: {data_str[:200]}")

        assert saw_done, "Stream did not end with 'data: [DONE]'"
        assert len(chunks) > 0, "Stream produced no data chunks before [DONE]"

        # Verify chunk structure (at least one content chunk)
        for chunk in chunks:
            assert "choices" in chunk, f"Chunk missing 'choices': {chunk}"


class TestRequestValidation:
    """POST /chat/completions must validate input via Pydantic."""

    async def test_missing_messages_returns_422(self, agent_url, http_client):
        """Request without 'messages' field must be rejected.

        Tests FastAPI's automatic Pydantic validation of
        ChatCompletionRequest — the messages field is required.
        """
        payload = {"stream": False}

        resp = await http_client.post(
            f"{agent_url}/chat/completions", json=payload, timeout=10.0
        )

        assert resp.status_code == 422, (
            f"Expected 422 for missing 'messages', got {resp.status_code}: {resp.text[:200]}"
        )

    async def test_empty_messages_list_handled(self, agent_url, http_client):
        """Empty messages list should return an error or graceful response.

        Tests edge case handling — an empty conversation has no user input.
        Agent should return 400/422 or handle gracefully, not crash with 500.
        """
        payload = {"messages": [], "stream": False}

        resp = await http_client.post(
            f"{agent_url}/chat/completions", json=payload, timeout=30.0
        )

        # Should not be a 500 (crash). 400, 422, or 200 with empty response are all acceptable.
        assert resp.status_code != 500, (
            f"Empty messages caused a server crash (500): {resp.text[:300]}"
        )


class TestAgentInitialization:
    """Agent must be initialized and ready to serve."""

    async def test_agent_ready_after_startup(self, agent_url, http_client):
        """A deployed agent must report agent_initialized=true.

        Tests the lifespan() startup hook in main.py — the agent graph/crew
        must be created during app startup, not lazily on first request.
        """
        resp = await http_client.get(f"{agent_url}/health", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        assert data["agent_initialized"] is True, (
            f"Agent not initialized after startup. Health: {data}"
        )

    async def test_health_status_is_healthy(self, agent_url, http_client):
        """A deployed agent should report a healthy status string."""
        resp = await http_client.get(f"{agent_url}/health", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        assert data["status"] == "healthy", (
            f"Expected status='healthy'. Got: {data}"
        )
