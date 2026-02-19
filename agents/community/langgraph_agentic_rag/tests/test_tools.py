import sys
import os
from unittest.mock import Mock, patch

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.langgraph_agentic_rag.tools import (
    retriever_tool,
    get_retriever_components,
    RetrieverInput
)


def test_retriever_tool_exists():
    """Test that the retriever tool is properly defined."""
    assert retriever_tool is not None
    assert retriever_tool.name == "retriever"
    assert retriever_tool.description is not None


def test_retriever_input_schema():
    """Test that the RetrieverInput schema is properly defined."""
    schema = RetrieverInput(query="test query")
    assert schema.query == "test query"


@patch('src.langgraph_agentic_rag.tools.get_retriever_components')
def test_retriever_tool_invoke_with_string_query(mock_get_components):
    """Test that the retriever tool can be invoked with a string query."""
    # Mock the LlamaStack client and vector store response
    mock_client = Mock()
    mock_chunk = Mock()
    mock_chunk.content = "LangGraph is a library for building stateful, multi-actor applications with LLMs."
    mock_chunk.score = 0.95
    mock_chunk.chunk_metadata = Mock(source="langgraph_docs.txt")

    mock_response = Mock()
    mock_response.chunks = [mock_chunk]

    mock_client.vector_io.query.return_value = mock_response

    mock_get_components.return_value = {
        "client": mock_client,
        "vector_store_id": "test-vector-store-id"
    }

    # Invoke the tool
    query = "What is LangGraph?"
    result = retriever_tool.invoke({"query": query})

    # Assertions
    assert isinstance(result, str)
    assert len(result) > 0
    assert "LangGraph" in result
    assert "Document 1" in result
    assert "Source:" in result
    assert "Score:" in result

    # Verify the client was called correctly
    mock_client.vector_io.query.assert_called_once_with(
        vector_store_id="test-vector-store-id",
        query=query,
        params={"max_chunks": 2}
    )


@patch('src.langgraph_agentic_rag.tools.get_retriever_components')
def test_retriever_tool_no_results(mock_get_components):
    """Test retriever tool behavior when no results are found."""
    # Mock empty response
    mock_client = Mock()
    mock_response = Mock()
    mock_response.chunks = []

    mock_client.vector_io.query.return_value = mock_response

    mock_get_components.return_value = {
        "client": mock_client,
        "vector_store_id": "test-vector-store-id"
    }

    # Invoke the tool
    result = retriever_tool.invoke({"query": "nonexistent query"})

    # Should return a message indicating no results
    assert "No relevant information was found" in result


@patch('src.langgraph_agentic_rag.tools.get_retriever_components')
def test_retriever_tool_multiple_chunks(mock_get_components):
    """Test retriever tool with multiple chunks returned."""
    # Mock multiple chunks
    mock_client = Mock()

    mock_chunk1 = Mock()
    mock_chunk1.content = "First document content about LangGraph."
    mock_chunk1.score = 0.95
    mock_chunk1.chunk_metadata = Mock(source="doc1.txt")

    mock_chunk2 = Mock()
    mock_chunk2.content = "Second document content about agents."
    mock_chunk2.score = 0.85
    mock_chunk2.chunk_metadata = Mock(source="doc2.txt")

    mock_response = Mock()
    mock_response.chunks = [mock_chunk1, mock_chunk2]

    mock_client.vector_io.query.return_value = mock_response

    mock_get_components.return_value = {
        "client": mock_client,
        "vector_store_id": "test-vector-store-id"
    }

    # Invoke the tool
    result = retriever_tool.invoke({"query": "LangGraph agents"})

    # Should contain both documents
    assert "Document 1" in result
    assert "Document 2" in result
    assert "First document" in result
    assert "Second document" in result
    assert "doc1.txt" in result
    assert "doc2.txt" in result


@patch('src.langgraph_agentic_rag.tools.get_retriever_components')
def test_retriever_tool_filters_empty_chunks(mock_get_components):
    """Test that empty or separator chunks are filtered out."""
    # Mock chunks with empty/separator content
    mock_client = Mock()

    mock_chunk1 = Mock()
    mock_chunk1.content = "====="  # Separator
    mock_chunk1.score = 0.90
    mock_chunk1.chunk_metadata = Mock(source="separator.txt")

    mock_chunk2 = Mock()
    mock_chunk2.content = "   "  # Whitespace only
    mock_chunk2.score = 0.88
    mock_chunk2.chunk_metadata = Mock(source="whitespace.txt")

    mock_chunk3 = Mock()
    mock_chunk3.content = "Actual content"  # Valid content
    mock_chunk3.score = 0.95
    mock_chunk3.chunk_metadata = Mock(source="valid.txt")

    mock_response = Mock()
    mock_response.chunks = [mock_chunk1, mock_chunk2, mock_chunk3]

    mock_client.vector_io.query.return_value = mock_response

    mock_get_components.return_value = {
        "client": mock_client,
        "vector_store_id": "test-vector-store-id"
    }

    # Invoke the tool
    result = retriever_tool.invoke({"query": "test"})

    # Should only contain the valid document
    assert "Document 1" in result
    assert "Actual content" in result
    assert "valid.txt" in result
    # Should not contain "Document 2" since separators were filtered
    assert "Document 2" not in result


@patch('src.langgraph_agentic_rag.tools.LlamaStackClient')
@patch('src.langgraph_agentic_rag.tools.get_env_var')
def test_get_retriever_components_initialization(mock_get_env, mock_client_class):
    """Test that retriever components are properly initialized."""
    # Reset cache
    import src.langgraph_agentic_rag.tools as tools_module
    tools_module._client_cache = None
    tools_module._vector_store_id_cache = None

    # Mock environment variable
    mock_get_env.return_value = "http://localhost:8321"

    # Mock client and vector store list
    mock_client = Mock()
    mock_vector_store = Mock()
    mock_vector_store.id = "test-vector-store-123"

    mock_list_response = Mock()
    mock_list_response.data = [mock_vector_store]

    mock_client.vector_stores.list.return_value = mock_list_response
    mock_client_class.return_value = mock_client

    # Call function
    result = get_retriever_components()

    # Assertions
    assert "client" in result
    assert "vector_store_id" in result
    assert result["vector_store_id"] == "test-vector-store-123"
    mock_client_class.assert_called_once_with(base_url="http://localhost:8321")


@patch('src.langgraph_agentic_rag.tools.LlamaStackClient')
@patch('src.langgraph_agentic_rag.tools.get_env_var')
def test_get_retriever_components_caching(mock_get_env, mock_client_class):
    """Test that retriever components are cached after first call."""
    # Set up cache with values
    import src.langgraph_agentic_rag.tools as tools_module
    mock_cached_client = Mock()
    tools_module._client_cache = mock_cached_client
    tools_module._vector_store_id_cache = "cached-vector-store-id"

    # Call function
    result = get_retriever_components()

    # Should return cached values without calling LlamaStackClient
    assert result["client"] == mock_cached_client
    assert result["vector_store_id"] == "cached-vector-store-id"
    mock_client_class.assert_not_called()


@patch('src.langgraph_agentic_rag.tools.LlamaStackClient')
def test_get_retriever_components_with_base_url(mock_client_class):
    """Test that base_url parameter is used when provided."""
    # Reset cache
    import src.langgraph_agentic_rag.tools as tools_module
    tools_module._client_cache = None
    tools_module._vector_store_id_cache = None

    # Mock client and vector store list
    mock_client = Mock()
    mock_vector_store = Mock()
    mock_vector_store.id = "test-id"

    mock_list_response = Mock()
    mock_list_response.data = [mock_vector_store]

    mock_client.vector_stores.list.return_value = mock_list_response
    mock_client_class.return_value = mock_client

    # Call with explicit base_url
    result = get_retriever_components(base_url="http://custom:9999")

    # Should use provided base_url
    mock_client_class.assert_called_once_with(base_url="http://custom:9999")
    assert result["vector_store_id"] == "test-id"


@patch('src.langgraph_agentic_rag.tools.LlamaStackClient')
@patch('src.langgraph_agentic_rag.tools.get_env_var')
def test_get_retriever_components_no_vector_store(mock_get_env, mock_client_class):
    """Test error handling when no vector store is found."""
    # Reset cache
    import src.langgraph_agentic_rag.tools as tools_module
    tools_module._client_cache = None
    tools_module._vector_store_id_cache = None

    mock_get_env.return_value = "http://localhost:8321"

    # Mock client with empty vector store list
    mock_client = Mock()
    mock_list_response = Mock()
    mock_list_response.data = []  # No vector stores

    mock_client.vector_stores.list.return_value = mock_list_response
    mock_client_class.return_value = mock_client

    # Should raise RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        get_retriever_components()

    assert "No vector store found" in str(exc_info.value)
    assert "load_documents.py" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
