from os import getenv
from typing import Any, Dict, Optional

from langchain_core.tools import tool
from llama_stack_client import LlamaStackClient
from pydantic import BaseModel, Field

# Cache to avoid re-initializing on every tool call
_client_cache = None
_vector_store_id_cache = None


def get_retriever_components(
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get the LlamaStack client and vector store ID for retrieval.

    Args:
        base_url: Base URL for the LlamaStack API

    Returns:
        Dict containing client and vector_store_id
    """
    global _client_cache, _vector_store_id_cache

    # Return cached components if they exist
    if _client_cache is not None and _vector_store_id_cache is not None:
        return {"client": _client_cache, "vector_store_id": _vector_store_id_cache}

    # Get configuration from environment if not provided
    if not base_url:
        base_url = getenv("BASE_URL")
    vector_store_id = getenv("VECTOR_STORE_ID")
    if not vector_store_id:
        raise RuntimeError(
            "VECTOR_STORE_ID env var is not set. Run load_documents.py first."
            "or check if you provided right ID"
        )

    if not base_url:
        raise ValueError("BASE_URL must be set in environment or passed as argument")

    # LlamaStackClient internally appends /v1, so strip it from base_url if present
    llama_base_url = base_url.rstrip("/").removesuffix("/v1")
    client = LlamaStackClient(
        base_url=llama_base_url,
        api_key=getenv("API_KEY"),
    )

    print(f"Using vector store: {vector_store_id}")

    # Cache the components
    _client_cache = client
    _vector_store_id_cache = vector_store_id

    return {"client": client, "vector_store_id": vector_store_id}


class RetrieverInput(BaseModel):
    """Schema for the retriever tool input."""

    query: str = Field(
        description="The search query describing what information you need to retrieve."
    )


@tool("retriever", args_schema=RetrieverInput)
def retriever_tool(query: str) -> str:
    """
    Search the knowledge base for information relevant to the query.

    Use this tool when you need to find specific information from the knowledge base
    to answer the user's question accurately.

    Args:
        query: The search query describing what information you need to retrieve.

    Returns:
        Retrieved documents containing relevant information.
    """
    # Handle case where query might be passed as a dict (defensive fix)
    if isinstance(query, dict):
        # Extract the actual query value from the dict
        query = query.get("value", query.get("query", str(query)))

    # Get retriever components
    components = get_retriever_components()
    client = components["client"]
    vector_store_id = components["vector_store_id"]

    # Query the vector store using LlamaStack client
    # The query parameter takes the text string, and the server handles embedding generation
    response = client.vector_io.query(
        vector_store_id=vector_store_id,
        query=query,  # Pass the text query directly
        params={
            "max_chunks": 5  # Retrieve only the most relevant document (max_chunks not top_k or K)
        },
    )

    # Format the retrieved documents
    if not response.chunks:
        return "No relevant information was found in the provided documents for this query."

    formatted_docs = []
    for i, chunk in enumerate(response.chunks, 1):
        # Skip chunks that are empty or just separators/whitespace
        content = chunk.content.strip()
        if not content or all(c in "=-_*#|" for c in content):
            continue

        # Extract source from chunk metadata (Pydantic object)
        source = (
            getattr(chunk.chunk_metadata, "source", "unknown")
            if hasattr(chunk, "chunk_metadata")
            else "unknown"
        )

        # Format each document with clear separation
        doc_text = f"--- Document {len(formatted_docs) + 1} ---\n"
        doc_text += f"Content: {content}\n"
        doc_text += f"Source: {source}\n"
        doc_text += f"Score: {getattr(chunk, 'score', 'N/A')}"

        formatted_docs.append(doc_text)

    # If all chunks were filtered out, return no information message
    if not formatted_docs:
        return "No relevant information was found in the provided documents for this query."

    return "\n\n".join(formatted_docs)
