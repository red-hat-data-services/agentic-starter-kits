import os
import sys
from os import getenv
from typing import Optional

# Fix sqlite3 version issue for chromadb (required by ai4rag)
# Must be done BEFORE importing ai4rag
try:
    import pysqlite3  # noqa: F401

    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass  # pysqlite3-binary not available, continue with system sqlite3

from ai4rag.rag.embedding.openai_model import (
    OpenAIEmbeddingModel,
    OpenAIEmbeddingParams,
)
from ai4rag.rag.retrieval.retriever import Retriever
from ai4rag.rag.vector_store import get_vector_store, get_vector_store_config
from langchain_core.tools import tool
from openai import OpenAI
from pydantic import BaseModel, Field

try:
    import mlflow
    from mlflow.entities import Document as MlflowDocument
except ImportError:
    mlflow = None

# Cache to avoid re-initializing on every tool call
_retriever_cache = None


def get_retriever(
    maas_api_key: Optional[str] = None,
    maas_base_url: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
    embedding_dimension: Optional[int] = None,
    milvus_collection: Optional[str] = None,
) -> Retriever:
    """
    Get or create the ai4rag retriever with MaaS embeddings and Milvus vector store.

    Args:
        maas_api_key: MaaS API key
        maas_base_url: MaaS base URL
        embedding_model_id: Embedding model identifier
        embedding_dimension: Embedding dimension
        milvus_collection: Milvus collection name

    Returns:
        ai4rag Retriever instance
    """
    global _retriever_cache

    # Handle MILVUS_SERVER_CERT FIRST - convert path to PEM text before anything else
    # This must be done before cache check and before ai4rag reads the env var
    milvus_cert = getenv("MILVUS_SERVER_CERT")
    if milvus_cert and not milvus_cert.startswith("-----BEGIN"):
        # It's a file path - read the certificate content
        if os.path.exists(milvus_cert):
            with open(milvus_cert, "r") as f:
                cert_content = f.read()
            os.environ["MILVUS_SERVER_CERT"] = cert_content
            print(f"✓ Loaded Milvus certificate from {milvus_cert}")
        else:
            print(
                f"⚠ Milvus cert file not found at {milvus_cert} - connection may fail"
            )
    elif milvus_cert and milvus_cert.startswith("-----BEGIN"):
        print("✓ Using Milvus certificate from environment (PEM text)")

    # Return cached retriever if it exists
    if _retriever_cache is not None:
        return _retriever_cache

    # Get configuration from environment if not provided
    if not maas_api_key:
        maas_api_key = getenv("MAAS_API_KEY")
    if not maas_base_url:
        maas_base_url = getenv("MAAS_BASE_URL")
    if not embedding_model_id:
        embedding_model_id = getenv("EMBEDDING_MODEL", "redhataibge-m3")
    if not embedding_dimension:
        embedding_dimension = int(getenv("EMBEDDING_DIMENSION", "1024"))
    if not milvus_collection:
        milvus_collection = getenv("MILVUS_COLLECTION_NAME")

    if not maas_api_key or not maas_base_url:
        raise ValueError("MAAS_API_KEY and MAAS_BASE_URL must be set")

    if not milvus_collection:
        raise RuntimeError(
            "MILVUS_COLLECTION_NAME env var is not set. Run load_documents_ai4rag.py first."
        )

    print(f"Using Milvus collection: {milvus_collection}")

    # Initialize MaaS client
    client = OpenAI(base_url=maas_base_url, api_key=maas_api_key)

    # Initialize embedding model
    params = OpenAIEmbeddingParams(
        embedding_dimension=embedding_dimension, context_length=1015
    )
    embedding_model = OpenAIEmbeddingModel(
        client=client, model_id=embedding_model_id, params=params
    )

    # Initialize Milvus vector store
    provider_type = "milvus"
    vector_store_config = get_vector_store_config(provider_type)
    vector_store = get_vector_store(
        embedding_model=embedding_model,
        config=vector_store_config,
        collection_name=milvus_collection,
    )

    # Create retriever with hybrid search
    retriever = Retriever(
        vector_store=vector_store,
        method="simple",
        number_of_chunks=5,
        search_mode="hybrid",
        ranker_strategy="weighted",
        ranker_alpha=0.5,
    )

    # Cache the retriever
    _retriever_cache = retriever

    return retriever


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

    # Get retriever
    retriever = get_retriever()

    # Retrieve documents
    retrieved_docs = retriever.retrieve(query)

    # Format the retrieved documents
    if not retrieved_docs or len(retrieved_docs) == 0:
        return "No relevant information was found in the provided documents for this query."

    formatted_docs = []
    retriever_docs = []
    for i, doc in enumerate(retrieved_docs, 1):
        # Skip chunks that are empty or just separators/whitespace
        # ai4rag returns AI4RAGChunk with .text attribute, not .page_content
        content = getattr(doc, "text", getattr(doc, "page_content", "")).strip()
        if not content or all(c in "=-_*#|" for c in content):
            continue

        # Extract source from metadata
        metadata = getattr(doc, "metadata", {})
        source = metadata.get("source", "unknown")

        # Extract score if available (ai4rag chunks may have score/similarity)
        score = getattr(doc, "score", getattr(doc, "similarity", None))
        score_str = f"{score:.3f}" if score is not None else "N/A"

        # Format each document with clear separation
        doc_text = f"--- Document {len(formatted_docs) + 1} ---\n"
        doc_text += f"Content: {content}\n"
        doc_text += f"Source: {source}\n"
        doc_text += f"Score: {score_str}"

        formatted_docs.append(doc_text)

        if mlflow:
            retriever_docs.append(
                MlflowDocument(
                    page_content=content,
                    metadata={"source": source, "score": getattr(doc, "score", None)},
                )
            )

    # Log RETRIEVER span for MLflow RAG evaluation scorers
    if mlflow and retriever_docs:
        with mlflow.start_span(name="retrieve", span_type="RETRIEVER") as span:
            span.set_inputs({"query": query})
            span.set_outputs(retriever_docs)

    # If all chunks were filtered out, return no information message
    if not formatted_docs:
        return "No relevant information was found in the provided documents for this query."

    return "\n\n".join(formatted_docs)
