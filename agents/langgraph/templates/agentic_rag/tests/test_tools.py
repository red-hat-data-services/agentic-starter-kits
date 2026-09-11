import os
import sys
from unittest.mock import Mock, patch

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agentic_rag.tools import (
    _initialize_retriever,
    create_retriever_tool,
    retriever_tool,
)


def test_retriever_tool_exists():
    """Test that the retriever tool is properly defined."""
    assert retriever_tool is not None
    assert retriever_tool.name == "retriever"
    assert retriever_tool.description is not None


@patch("src.agentic_rag.tools._initialize_retriever")
def test_retriever_tool_invoke_with_string_query(mock_initialize_retriever):
    """Test that the retriever tool can be invoked with a string query."""
    # Mock ai4rag retriever and chunks
    mock_retriever = Mock()
    mock_chunk = Mock()
    mock_chunk.text = "LangGraph is a library for building stateful, multi-actor applications with LLMs."
    mock_chunk.score = 0.95
    mock_chunk.metadata = {"source": "langgraph_docs.txt"}

    mock_retriever.retrieve.return_value = [mock_chunk]
    mock_initialize_retriever.return_value = mock_retriever

    # Create fresh tool instance for this test
    test_tool = create_retriever_tool()

    # Invoke the tool
    query = "What is LangGraph?"
    result = test_tool.invoke({"query": query})

    # Assertions
    assert isinstance(result, str)
    assert len(result) > 0
    assert "LangGraph" in result
    assert "Document 1" in result
    assert "Source:" in result
    assert "Score:" in result

    # Verify the retriever was called correctly
    mock_retriever.retrieve.assert_called_once_with(query)


@patch("src.agentic_rag.tools._initialize_retriever")
def test_retriever_tool_no_results(mock_initialize_retriever):
    """Test retriever tool behavior when no results are found."""
    # Mock empty response
    mock_retriever = Mock()
    mock_retriever.retrieve.return_value = []
    mock_initialize_retriever.return_value = mock_retriever

    # Create fresh tool instance for this test
    test_tool = create_retriever_tool()

    # Invoke the tool
    result = test_tool.invoke({"query": "nonexistent query"})

    # Should return a message indicating no results
    assert "No relevant information was found" in result


@patch("src.agentic_rag.tools._initialize_retriever")
def test_retriever_tool_multiple_chunks(mock_initialize_retriever):
    """Test retriever tool with multiple chunks returned."""
    # Mock multiple chunks
    mock_retriever = Mock()

    mock_chunk1 = Mock()
    mock_chunk1.text = "First document content about LangGraph."
    mock_chunk1.score = 0.95
    mock_chunk1.metadata = {"source": "doc1.txt"}

    mock_chunk2 = Mock()
    mock_chunk2.text = "Second document content about agents."
    mock_chunk2.score = 0.85
    mock_chunk2.metadata = {"source": "doc2.txt"}

    mock_retriever.retrieve.return_value = [mock_chunk1, mock_chunk2]
    mock_initialize_retriever.return_value = mock_retriever

    # Create fresh tool instance for this test
    test_tool = create_retriever_tool()

    # Invoke the tool
    result = test_tool.invoke({"query": "LangGraph agents"})

    # Should contain both documents
    assert "Document 1" in result
    assert "Document 2" in result
    assert "First document" in result
    assert "Second document" in result
    assert "doc1.txt" in result
    assert "doc2.txt" in result


@patch("src.agentic_rag.tools._initialize_retriever")
def test_retriever_tool_filters_empty_chunks(mock_initialize_retriever):
    """Test that empty or separator chunks are filtered out."""
    # Mock chunks with empty/separator content
    mock_retriever = Mock()

    mock_chunk1 = Mock()
    mock_chunk1.text = "====="  # Separator
    mock_chunk1.score = 0.90
    mock_chunk1.metadata = {"source": "separator.txt"}

    mock_chunk2 = Mock()
    mock_chunk2.text = "   "  # Whitespace only
    mock_chunk2.score = 0.88
    mock_chunk2.metadata = {"source": "whitespace.txt"}

    mock_chunk3 = Mock()
    mock_chunk3.text = "Actual content"  # Valid content
    mock_chunk3.score = 0.95
    mock_chunk3.metadata = {"source": "valid.txt"}

    mock_retriever.retrieve.return_value = [mock_chunk1, mock_chunk2, mock_chunk3]
    mock_initialize_retriever.return_value = mock_retriever

    # Create fresh tool instance for this test
    test_tool = create_retriever_tool()

    # Invoke the tool
    result = test_tool.invoke({"query": "test"})

    # Should only contain the valid document
    assert "Document 1" in result
    assert "Actual content" in result
    assert "valid.txt" in result
    # Should not contain "Document 2" since separators were filtered
    assert "Document 2" not in result


@patch("src.agentic_rag.tools.get_vector_store")
@patch("src.agentic_rag.tools.get_vector_store_config")
@patch("src.agentic_rag.tools.Retriever")
@patch("src.agentic_rag.tools.OpenAI")
@patch("src.agentic_rag.tools.getenv")
def test_initialize_retriever_initialization(
    mock_get_env,
    mock_openai_class,
    mock_retriever_class,
    mock_get_config,
    mock_get_store,
):
    """Test that retriever is properly initialized."""

    # Mock environment variables (getenv can have default as 2nd arg)
    def getenv_side_effect(key, default=None):
        return {
            "MAAS_API_KEY": "test-maas-key",
            "MAAS_BASE_URL": "https://maas.example.com/v1",
            "MILVUS_COLLECTION_NAME": "test-collection-123",
            "EMBEDDING_MODEL_ID": "test-embedding-model",
            "EMBEDDING_DIMENSION": "1024",
        }.get(key, default)

    mock_get_env.side_effect = getenv_side_effect
    mock_get_config.return_value = Mock()
    mock_get_store.return_value = Mock()
    mock_retriever_class.return_value = Mock()

    # Call function
    result = _initialize_retriever()

    # Assertions
    assert result is not None
    mock_openai_class.assert_called_once_with(
        base_url="https://maas.example.com/v1", api_key="test-maas-key"
    )


@patch("src.agentic_rag.tools._initialize_retriever")
def test_retriever_tool_caching(mock_initialize_retriever):
    """Test that retriever is cached after first call within a tool instance."""
    # Mock retriever
    mock_retriever = Mock()
    mock_chunk = Mock()
    mock_chunk.text = "Test content"
    mock_chunk.score = 0.95
    mock_chunk.metadata = {"source": "test.txt"}
    mock_retriever.retrieve.return_value = [mock_chunk]
    mock_initialize_retriever.return_value = mock_retriever

    # Create a tool instance
    test_tool = create_retriever_tool()

    # Call the tool twice
    test_tool.invoke({"query": "first query"})
    test_tool.invoke({"query": "second query"})

    # _initialize_retriever should only be called once (cached on second call)
    assert mock_initialize_retriever.call_count == 1
    # But retrieve should be called twice
    assert mock_retriever.retrieve.call_count == 2


@patch("src.agentic_rag.tools.get_vector_store")
@patch("src.agentic_rag.tools.get_vector_store_config")
@patch("src.agentic_rag.tools.Retriever")
@patch("src.agentic_rag.tools.OpenAI")
@patch("src.agentic_rag.tools.getenv")
def test_initialize_retriever_uses_environment_params(
    mock_get_env,
    mock_openai_class,
    mock_retriever_class,
    mock_get_config,
    mock_get_store,
):
    """Test that retriever configuration is read from environment variables."""

    def getenv_side_effect(key, default=None):
        return {
            "MAAS_API_KEY": "custom-key",
            "MAAS_BASE_URL": "https://custom.example.com/v1",
            "MILVUS_COLLECTION_NAME": "env-collection",
            "EMBEDDING_MODEL_ID": "test-embedding-model",
            "EMBEDDING_DIMENSION": "1024",
        }.get(key, default)

    mock_get_env.side_effect = getenv_side_effect
    mock_get_config.return_value = Mock()
    mock_get_store.return_value = Mock()
    mock_retriever_class.return_value = Mock()

    result = _initialize_retriever()

    # Should use values from the environment
    mock_openai_class.assert_called_once_with(
        base_url="https://custom.example.com/v1", api_key="custom-key"
    )
    assert result is not None


@patch("src.agentic_rag.tools.getenv")
def test_initialize_retriever_no_collection(mock_get_env):
    """Test error handling when the configured collection is not set."""

    def getenv_side_effect(key, default=None):
        return {
            "MAAS_API_KEY": "test-key",
            "MAAS_BASE_URL": "https://maas.example.com/v1",
            "EMBEDDING_MODEL_ID": "test-model",
            "EMBEDDING_DIMENSION": "1024",
        }.get(key, default)

    mock_get_env.side_effect = getenv_side_effect

    with pytest.raises(ValueError) as exc_info:
        _initialize_retriever()

    assert "Collection name for provider 'milvus' must be set" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
