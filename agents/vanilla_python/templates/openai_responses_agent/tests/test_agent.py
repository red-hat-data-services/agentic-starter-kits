from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from openai import APIStatusError
from openai_responses_agent.agent import AIAgent, _get_output_text_from_response


class TestGetOutputTextFromResponse:
    def test_chat_completions_format(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))]
        )
        assert _get_output_text_from_response(response) == "hello"

    def test_chat_completions_none_content(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        )
        assert _get_output_text_from_response(response) == ""

    def test_responses_api_format(self):
        block = SimpleNamespace(type="output_text", text="world")
        item = SimpleNamespace(content=[block])
        response = SimpleNamespace(output=[item])
        assert _get_output_text_from_response(response) == "world"

    def test_empty_response(self):
        response = SimpleNamespace()
        assert _get_output_text_from_response(response) == ""


class TestLLMCreateFallback:
    @patch("openai_responses_agent.agent.OpenAI")
    def _make_agent(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        agent = AIAgent(model="test-model", base_url="http://localhost:8000")
        return agent, mock_client

    def test_responses_api_success_caches_result(self):
        agent, mock_client = self._make_agent()
        mock_response = SimpleNamespace(
            output=[
                SimpleNamespace(
                    content=[SimpleNamespace(type="output_text", text="ok")]
                )
            ]
        )
        mock_client.responses.create.return_value = mock_response

        agent.messages = [{"role": "user", "content": "hi"}]
        result = agent._llm_create(messages=agent.messages)

        assert result is mock_response
        assert agent._use_responses_api is True
        mock_client.responses.create.assert_called_once()
        mock_client.chat.completions.create.assert_not_called()

    def test_fallback_on_400(self):
        agent, mock_client = self._make_agent()
        mock_response = MagicMock()
        exc = APIStatusError(
            message="Bad Request",
            response=MagicMock(status_code=400, headers={}),
            body=None,
        )
        mock_client.responses.create.side_effect = exc
        mock_client.chat.completions.create.return_value = mock_response

        agent.messages = [{"role": "user", "content": "hi"}]
        result = agent._llm_create(messages=agent.messages)

        assert result is mock_response
        assert agent._use_responses_api is None
        mock_client.chat.completions.create.assert_called_once()

    def test_fallback_on_404(self):
        agent, mock_client = self._make_agent()
        mock_response = MagicMock()
        exc = APIStatusError(
            message="Not Found",
            response=MagicMock(status_code=404, headers={}),
            body=None,
        )
        mock_client.responses.create.side_effect = exc
        mock_client.chat.completions.create.return_value = mock_response

        agent.messages = [{"role": "user", "content": "hi"}]
        result = agent._llm_create(messages=agent.messages)

        assert result is mock_response
        assert agent._use_responses_api is False

    def test_non_fallback_error_propagates(self):
        agent, mock_client = self._make_agent()
        exc = APIStatusError(
            message="Internal Server Error",
            response=MagicMock(status_code=500, headers={}),
            body=None,
        )
        mock_client.responses.create.side_effect = exc

        agent.messages = [{"role": "user", "content": "hi"}]
        with pytest.raises(APIStatusError):
            agent._llm_create(messages=agent.messages)

        assert agent._use_responses_api is None
        mock_client.chat.completions.create.assert_not_called()

    def test_cached_fallback_skips_probe(self):
        agent, mock_client = self._make_agent()
        mock_response = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        agent._use_responses_api = False
        agent.messages = [{"role": "user", "content": "hi"}]
        result = agent._llm_create(messages=agent.messages)

        assert result is mock_response
        mock_client.responses.create.assert_not_called()
        mock_client.chat.completions.create.assert_called_once()

    def test_temperature_zero_is_passed(self):
        """temperature=0 must be included in API kwargs, not omitted."""
        agent, mock_client = self._make_agent()
        mock_client.chat.completions.create.return_value = MagicMock()

        agent._use_responses_api = False
        agent.messages = [{"role": "user", "content": "hi"}]
        agent._llm_create(messages=agent.messages)

        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs[1]["temperature"] == 0

    def test_fallback_on_400_after_prior_success(self):
        """400 after a prior Responses API success falls back without caching."""
        agent, mock_client = self._make_agent()
        mock_response = MagicMock()
        exc = APIStatusError(
            message="Bad Request",
            response=MagicMock(status_code=400, headers={}),
            body=None,
        )
        mock_client.responses.create.side_effect = exc
        mock_client.chat.completions.create.return_value = mock_response

        agent._use_responses_api = True
        agent.messages = [{"role": "user", "content": "multi-turn message"}]
        result = agent._llm_create(messages=agent.messages)

        assert result is mock_response
        assert agent._use_responses_api is True
        mock_client.chat.completions.create.assert_called_once()

    def test_fallback_on_404_after_prior_success(self):
        """404 after a prior Responses API success permanently disables it."""
        agent, mock_client = self._make_agent()
        mock_response = MagicMock()
        exc = APIStatusError(
            message="Not Found",
            response=MagicMock(status_code=404, headers={}),
            body=None,
        )
        mock_client.responses.create.side_effect = exc
        mock_client.chat.completions.create.return_value = mock_response

        agent._use_responses_api = True
        agent.messages = [{"role": "user", "content": "multi-turn message"}]
        result = agent._llm_create(messages=agent.messages)

        assert result is mock_response
        assert agent._use_responses_api is False
        mock_client.chat.completions.create.assert_called_once()
