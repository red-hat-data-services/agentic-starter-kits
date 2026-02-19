import sys
import os

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.langgraph_react_agent_base.tools import (
    dummy_web_search,
    dummy_math,
    SearchInput,
    MathInput,
)


def test_dummy_web_search_exists():
    """Test that the dummy_web_search tool is properly defined."""
    assert dummy_web_search is not None
    assert dummy_web_search.name == "search"
    assert dummy_web_search.description is not None


def test_dummy_math_exists():
    """Test that the dummy_math tool is properly defined."""
    assert dummy_math is not None
    assert dummy_math.name == "add"
    assert dummy_math.description is not None


def test_search_input_schema():
    """Test that the SearchInput schema is properly defined."""
    schema = SearchInput(query="test search")
    assert schema.query == "test search"


def test_math_input_schema():
    """Test that the MathInput schema is properly defined."""
    schema = MathInput(query="2 + 2")
    assert schema.query == "2 + 2"


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


def test_dummy_math_invoke_with_string():
    """Test that dummy_math can be invoked with a string query."""
    query = "2 + 2"
    result = dummy_math.invoke({"query": query})

    # Assertions
    assert isinstance(result, list)
    assert len(result) > 0
    assert result[0] == "Math response"


def test_dummy_math_invoke_different_queries():
    """Test that dummy_math works with different query strings."""
    queries = ["5 * 10", "100 / 4", "sqrt(16)", "calculate pi"]

    for query in queries:
        result = dummy_math.invoke({"query": query})
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == "Math response"  # Always returns same placeholder


def test_dummy_math_return_format():
    """Test that dummy_math returns the expected format."""
    result = dummy_math.invoke({"query": "10 + 5"})

    # Should be a list of strings
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], str)
    assert result[0] == "Math response"


def test_tool_schemas_have_descriptions():
    """Test that tool input schemas have field descriptions."""
    # SearchInput schema
    search_schema = SearchInput.model_json_schema()
    assert "properties" in search_schema
    assert "query" in search_schema["properties"]
    assert "description" in search_schema["properties"]["query"]

    # MathInput schema
    math_schema = MathInput.model_json_schema()
    assert "properties" in math_schema
    assert "query" in math_schema["properties"]
    assert "description" in math_schema["properties"]["query"]


def test_tools_work_with_langchain_invoke():
    """Test that tools are compatible with LangChain's invoke interface."""
    # Test web search
    search_result = dummy_web_search.invoke({"query": "test query"})
    assert search_result is not None

    # Test math
    math_result = dummy_math.invoke({"query": "test calculation"})
    assert math_result is not None


def test_dummy_web_search_with_empty_query():
    """Test dummy_web_search behavior with empty query."""
    result = dummy_web_search.invoke({"query": ""})

    # Even with empty query, should return the placeholder response
    assert isinstance(result, str)
    assert "RedHat" in result


def test_dummy_math_with_empty_query():
    """Test dummy_math behavior with empty query."""
    result = dummy_math.invoke({"query": ""})

    # Even with empty query, should return the placeholder response
    assert isinstance(result, list)
    assert result[0] == "Math response"


def test_tool_names_are_correct():
    """Test that tool names match expected values."""
    assert dummy_web_search.name == "search"
    assert dummy_math.name == "add"


def test_tools_have_args_schema():
    """Test that tools have properly configured args schemas."""
    # Web search should infer schema from docstring (parse_docstring=True)
    assert hasattr(dummy_web_search, "args_schema")

    # Math tool has explicit args_schema
    assert hasattr(dummy_math, "args_schema")
    assert dummy_math.args_schema == MathInput


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
