import sys
from os import getenv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlite_shim import patch_sqlite3

patch_sqlite3()

from ai4rag.rag.embedding.openai_model import (  # noqa: E402
    OpenAIEmbeddingModel,
    OpenAIEmbeddingParams,
)
from ai4rag.rag.retrieval.retriever import Retriever  # noqa: E402
from ai4rag.rag.vector_store import (  # noqa: E402
    get_vector_store,
    get_vector_store_config,
)
from langchain_core.tools import tool  # noqa: E402
from openai import OpenAI  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agentic_rag.config import AgentConfig  # noqa: E402

try:
    import mlflow
    from mlflow.entities import Document as MlflowDocument
except ImportError:
    mlflow = None


def _initialize_retriever() -> Retriever:
    """Initialize the retriever from the starter-kit environment."""

    maas_api_key = getenv("MAAS_API_KEY")
    maas_base_url = getenv("MAAS_BASE_URL")
    embedding_model_id = getenv("EMBEDDING_MODEL_ID")
    embedding_dimension = int(getenv("EMBEDDING_DIMENSION", "768"))
    provider_type = getenv("PROVIDER_TYPE", "milvus").lower()
    collection_name = getenv(
        "MILVUS_COLLECTION_NAME"
        if provider_type == "milvus"
        else "PGVECTOR_COLLECTION_NAME"
    )

    if not maas_api_key or not maas_base_url:
        raise ValueError("MAAS_API_KEY and MAAS_BASE_URL must be set")
    if not embedding_model_id:
        raise ValueError("EMBEDDING_MODEL_ID must be set")
    if not collection_name:
        raise ValueError(f"Collection name for provider {provider_type!r} must be set")
    if not maas_base_url.startswith("https://"):
        raise ValueError("MAAS_BASE_URL must use HTTPS to protect API key transmission")

    client = OpenAI(base_url=maas_base_url, api_key=maas_api_key)
    embedding_model = OpenAIEmbeddingModel(
        client=client,
        model_id=embedding_model_id,
        params=OpenAIEmbeddingParams(
            embedding_dimension=embedding_dimension, context_length=1015
        ),
    )
    vector_store = get_vector_store(
        embedding_model=embedding_model,
        config=get_vector_store_config(provider_type),
        collection_name=collection_name,
    )

    ranker_alpha = getenv("RANKER_ALPHA")
    return Retriever(
        vector_store=vector_store,
        method=getenv("RETRIEVAL_METHOD", "simple"),
        number_of_chunks=int(getenv("NUMBER_OF_CHUNKS", "5")),
        search_mode=getenv("SEARCH_MODE", "vector"),
        ranker_strategy=getenv("RANKER_STRATEGY") or None,
        ranker_alpha=float(ranker_alpha) if ranker_alpha else None,
    )


def create_retriever_tool():
    """Create a retriever tool with a lazily initialized retriever."""
    retriever_cache = None

    class RetrieverInput(BaseModel):
        query: str = Field(
            description="The search query describing what information to retrieve."
        )

    @tool("retriever", args_schema=RetrieverInput)
    def retriever_tool(query: str) -> str:
        """Search the knowledge base for information relevant to the query."""
        nonlocal retriever_cache
        if isinstance(query, dict):
            query = query.get("value", query.get("query", str(query)))
        if retriever_cache is None:
            retriever_cache = _initialize_retriever()

        retrieved_docs = retriever_cache.retrieve(query)
        if not retrieved_docs:
            return "No relevant information was found in the provided documents for this query."

        config = AgentConfig.from_env()
        formatted_docs = []
        retriever_docs = []
        for doc in retrieved_docs:
            content = (
                getattr(doc, "text", getattr(doc, "page_content", "")) or ""
            ).strip()
            if not content or all(c in "=-_*#|" for c in content):
                continue
            metadata = getattr(doc, "metadata", None) or {}
            source = metadata.get("source", "unknown")
            score = getattr(doc, "score", getattr(doc, "similarity", None))
            score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "N/A"
            formatted_docs.append(
                f"--- Document {len(formatted_docs) + 1} ---\nContent: {content}\nSource: {source}\nScore: {score_str}"
            )
            if mlflow:
                retriever_docs.append(
                    MlflowDocument(
                        page_content=content,
                        metadata={"source": source, "score": score},
                    )
                )

        if mlflow and retriever_docs:
            with mlflow.start_span(name="retrieve", span_type="RETRIEVER") as span:
                span.set_inputs({"query": query})
                span.set_outputs(retriever_docs)
        if not formatted_docs:
            return "No relevant information was found in the provided documents for this query."

        context = "\n\n".join(
            config.context_template.format(document=document, doc_number=index)
            for index, document in enumerate(formatted_docs, 1)
        )
        return config.user_message_template.format(
            reference_documents=context, question=query
        )

    return retriever_tool


retriever_tool = create_retriever_tool()
