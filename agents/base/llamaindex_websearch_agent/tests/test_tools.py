import sys
import os

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.llama_index_workflow_agent_base.tools import dummy_web_search


def test_dummy_web_search_exists():
    """Test that the dummy_web_search function is properly defined."""
    assert dummy_web_search is not None
    assert callable(dummy_web_search)


def test_dummy_web_search_basic_invocation():
    """Test that dummy_web_search can be called with a string query."""
    query = "RedHat"
    result = dummy_web_search(query)

    # Assertions
    assert isinstance(result, list)
    assert len(result) > 0
    assert "RedHat" in result[0]


def test_dummy_web_search_return_type():
    """Test that dummy_web_search returns a list of strings."""
    result = dummy_web_search("test query")

    # Should return a list
    assert isinstance(result, list)
    # All elements should be strings
    for item in result:
        assert isinstance(item, str)


def test_dummy_web_search_return_value():
    """Test that dummy_web_search returns the expected static value."""
    result = dummy_web_search("any query")

    # Should always return ["RedHat"]
    assert result == ["RedHat"]
    assert len(result) == 1
    assert result[0] == "RedHat"


def test_dummy_web_search_with_different_queries():
    """Test that dummy_web_search works with different query strings."""
    queries = ["OpenShift", "LangGraph", "artificial intelligence", "test", "123"]

    for query in queries:
        result = dummy_web_search(query)
        assert isinstance(result, list)
        assert result == ["RedHat"]  # Always returns same static value


def test_dummy_web_search_with_empty_query():
    """Test dummy_web_search behavior with empty string."""
    result = dummy_web_search("")

    # Even with empty query, should return the static response
    assert isinstance(result, list)
    assert result == ["RedHat"]


def test_dummy_web_search_with_special_characters():
    """Test dummy_web_search with special characters in query."""
    special_queries = [
        "query with spaces",
        "query-with-dashes",
        "query_with_underscores",
        "query@with#symbols",
        "query\nwith\nnewlines",
    ]

    for query in special_queries:
        result = dummy_web_search(query)
        assert result == ["RedHat"]


def test_dummy_web_search_deterministic():
    """Test that dummy_web_search always returns the same result."""
    query = "test"
    result1 = dummy_web_search(query)
    result2 = dummy_web_search(query)
    result3 = dummy_web_search(query)

    # All calls should return identical results
    assert result1 == result2 == result3
    assert result1 == ["RedHat"]


def test_dummy_web_search_docstring():
    """Test that dummy_web_search has proper documentation."""
    assert dummy_web_search.__doc__ is not None
    assert "Web search" in dummy_web_search.__doc__
    assert "Args:" in dummy_web_search.__doc__
    assert "Returns:" in dummy_web_search.__doc__


def test_dummy_web_search_function_signature():
    """Test that dummy_web_search has the correct function signature."""
    import inspect

    # Get function signature
    sig = inspect.signature(dummy_web_search)
    params = list(sig.parameters.keys())

    # Should have exactly one parameter named 'query'
    assert len(params) == 1
    assert params[0] == "query"


def test_dummy_web_search_type_hints():
    """Test that dummy_web_search has proper type hints."""
    import inspect

    # Get type hints
    hints = inspect.get_annotations(dummy_web_search)

    # Should have type hints for query and return
    assert "query" in hints
    assert "return" in hints
    assert isinstance(hints["query"], str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
