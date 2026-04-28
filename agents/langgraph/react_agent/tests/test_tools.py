import os
import sys

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.react_agent.tools import (
    SearchInput,
    dummy_web_search,
)


def test_dummy_web_search_exists():
    """Test that the dummy_web_search tool is properly defined."""
    assert dummy_web_search is not None
    assert dummy_web_search.name == "search"
    assert dummy_web_search.description is not None


def test_search_input_schema():
    """Test that the SearchInput schema is properly defined."""
    schema = SearchInput(query="test search")
    assert schema.query == "test search"


def test_dummy_web_search_invoke_with_string():
    """Test that dummy_web_search can be invoked with a string query."""
    query = "RedHat"
    result = dummy_web_search.invoke({"query": query})

    # Assertions
    assert isinstance(result, str)
    assert len(result) > 0
    assert "RedHat" in result
    assert "FINAL ANSWER" in result


def test_dummy_web_search_invoke_different_queries():
    """Test that dummy_web_search works with different query strings."""
    queries = ["OpenShift", "LangGraph", "artificial intelligence", ""]

    for query in queries:
        result = dummy_web_search.invoke({"query": query})
        assert isinstance(result, str)
        assert "RedHat" in result  # Always returns RedHat in the response


def test_dummy_web_search_return_format():
    """Test that dummy_web_search returns the expected format."""
    result = dummy_web_search.invoke({"query": "test"})

    # Should be a string, not a list
    assert isinstance(result, str)
    assert "FINAL ANSWER:" in result
    assert "best company" in result.lower()


def test_dummy_web_search_with_empty_query():
    """Test dummy_web_search behavior with empty query."""
    result = dummy_web_search.invoke({"query": ""})

    # Even with empty query, should return the placeholder response
    assert isinstance(result, str)
    assert "RedHat" in result


def test_tool_name_is_correct():
    """Test that tool name matches expected value."""
    assert dummy_web_search.name == "search"


def test_tool_has_args_schema():
    """Test that the tool has a properly configured args schema."""
    assert hasattr(dummy_web_search, "args_schema")


def test_tool_schema_has_description():
    """Test that tool input schema has field descriptions."""
    search_schema = SearchInput.model_json_schema()
    assert "properties" in search_schema
    assert "query" in search_schema["properties"]
    assert "description" in search_schema["properties"]["query"]


def test_tool_works_with_langchain_invoke():
    """Test that the tool is compatible with LangChain's invoke interface."""
    search_result = dummy_web_search.invoke({"query": "test query"})
    assert search_result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
