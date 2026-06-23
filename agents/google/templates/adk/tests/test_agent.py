import os

import pytest
from adk_agent.agent import APP_NAME, get_agent, get_runner

ENV_KEYS = {"API_KEY", "BASE_URL", "MODEL_ID", "OPENAI_API_BASE", "OPENAI_API_KEY"}


@pytest.fixture(autouse=True)
def restore_llm_environment():
    original = {key: os.environ.get(key) for key in ENV_KEYS}
    for key in ENV_KEYS:
        os.environ.pop(key, None)

    yield

    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_get_agent_normalizes_local_base_url():
    agent = get_agent(model_id="demo-model", base_url="http://localhost:8321")

    assert agent.name == APP_NAME
    assert agent.model.model == "openai/demo-model"
    assert os.environ["OPENAI_API_BASE"] == "http://localhost:8321/v1"
    assert os.environ["OPENAI_API_KEY"] == "not-needed-for-local-development"
    assert len(agent.tools) == 1


def test_get_agent_uses_environment_defaults():
    os.environ["MODEL_ID"] = "env-model"
    os.environ["BASE_URL"] = "http://127.0.0.1:8321/"

    agent = get_agent()

    assert agent.model.model == "openai/env-model"
    assert os.environ["OPENAI_API_BASE"] == "http://127.0.0.1:8321/v1"
    assert os.environ["OPENAI_API_KEY"] == "not-needed-for-local-development"


def test_get_agent_requires_api_key_for_remote_base_url():
    with pytest.raises(
        ValueError, match="API_KEY is required for non-local environments."
    ):
        get_agent(model_id="demo-model", base_url="https://example.com")


def test_get_runner_uses_app_name():
    runner = get_runner(model_id="demo-model", base_url="http://localhost:8321")

    assert runner.app_name == APP_NAME
    assert runner.agent.name == APP_NAME
