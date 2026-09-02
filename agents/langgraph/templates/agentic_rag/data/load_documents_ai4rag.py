"""
Script to load documents from text files into Milvus using ai4rag.

Uses MaaS for embeddings and Milvus for vector storage.
The collection name is taken from MILVUS_COLLECTION_NAME env var or auto-generated.

NOTE: Use load_documents_wrapper.py as entry point to fix sqlite3 issue.
"""

import os
import uuid
from datetime import datetime

from ai4rag.rag.embedding.openai_model import (
    OpenAIEmbeddingModel,
    OpenAIEmbeddingParams,
)
from ai4rag.rag.vector_store import get_vector_store, get_vector_store_config
from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI

load_dotenv(verbose=True)


def load_and_index_documents(
    docs_to_load: str | None = None,
    chunk_size: int = 512,
    chunk_overlap: int = 128,
):
    """
    Load documents from directory and index them in Milvus using ai4rag.

    Args:
        docs_to_load: Path to text file to load
        chunk_size: Size of text chunks
        chunk_overlap: Overlap between chunks
    """
    # Get MaaS configuration
    maas_api_key = os.getenv("MAAS_API_KEY")
    maas_base_url = os.getenv("MAAS_BASE_URL")
    embedding_model_id = os.getenv("EMBEDDING_MODEL", "redhataibge-m3")
    embedding_dimension = int(os.getenv("EMBEDDING_DIMENSION", "1024"))

    # Get Milvus configuration
    milvus_uri = os.getenv("MILVUS_URI")
    milvus_token = os.getenv("MILVUS_TOKEN")
    milvus_cert = os.getenv("MILVUS_SERVER_CERT")  # None if not set, empty string if set to ""

    # Generate a unique collection name with timestamp if not provided
    milvus_collection = os.getenv("MILVUS_COLLECTION_NAME")
    if not milvus_collection:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        random_suffix = uuid.uuid4().hex[:8]
        milvus_collection = f"ai4rag_{timestamp}_{random_suffix}"

    if not maas_api_key or not maas_base_url:
        raise ValueError("MAAS_API_KEY and MAAS_BASE_URL must be set")

    if not milvus_uri:
        raise ValueError("MILVUS_URI must be set")

    # Handle MILVUS_SERVER_CERT - can be PEM text or path to file
    # If it looks like a file path (doesn't start with -----BEGIN), read it
    # Otherwise, assume it's already PEM text
    if milvus_cert and not milvus_cert.startswith("-----BEGIN"):
        # It's a file path - read the certificate content
        if not os.path.exists(milvus_cert):
            raise ValueError(f"MILVUS_SERVER_CERT file not found at {milvus_cert}")
        with open(milvus_cert, 'r') as f:
            cert_content = f.read()
        os.environ["MILVUS_SERVER_CERT"] = cert_content
        print(f"✓ Loaded certificate from {milvus_cert}")
    elif milvus_cert and milvus_cert.startswith("-----BEGIN"):
        # It's already PEM text - use it directly
        os.environ["MILVUS_SERVER_CERT"] = milvus_cert
        print("✓ Using certificate from environment variable (PEM text)")
    else:
        print("⚠ No MILVUS_SERVER_CERT provided - connection may fail if TLS is required")

    # Set other environment variables for ai4rag
    os.environ["MILVUS_URI"] = milvus_uri
    if milvus_token:
        os.environ["MILVUS_TOKEN"] = milvus_token

    if not docs_to_load:
        docs_to_load = os.getenv("DOCUMENTS_DIR", "./data") + "/sample_knowledge.txt"

    print(f"Loading documents from: {docs_to_load}")
    print(f"Using MaaS embedding model: {embedding_model_id}")
    print(f"Using Milvus collection: {milvus_collection}")

    # Initialize MaaS client
    client = OpenAI(base_url=maas_base_url, api_key=maas_api_key)

    # Initialize embedding model
    params = OpenAIEmbeddingParams(
        embedding_dimension=embedding_dimension,
        context_length=1015
    )
    embedding_model = OpenAIEmbeddingModel(
        client=client,
        model_id=embedding_model_id,
        params=params
    )

    # Initialize Milvus vector store
    provider_type = "milvus"
    vector_store_config = get_vector_store_config(provider_type)
    vector_store = get_vector_store(
        embedding_model=embedding_model,
        config=vector_store_config,
        collection_name=milvus_collection,
    )

    print("Loading documents from file...")
    loader = TextLoader(docs_to_load)
    documents = loader.load()

    print("\nSplitting documents into chunks...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    all_chunks = text_splitter.split_documents(documents)

    # Filter out chunks that are empty, just whitespace, or just separator lines
    chunks = []
    for doc in all_chunks:
        content = doc.page_content.strip()
        if content and not all(c in "=-_*#|\n\r\t " for c in content):
            chunks.append(doc)

    print(f"Created {len(chunks)} chunks (filtered out empty/separator chunks)")

    if len(chunks) == 0:
        print("No valid chunks to index. Exiting.")
        return

    print("\nIndexing documents in Milvus...")
    # Convert LangChain Documents to ai4rag AI4RAGChunk format
    from ai4rag.rag.chunking.chunk import AI4RAGChunk

    ai4rag_chunks = []
    for chunk in chunks:
        ai4rag_chunk = AI4RAGChunk(
            text=chunk.page_content,
            metadata=chunk.metadata,
        )
        ai4rag_chunks.append(ai4rag_chunk)

    # ai4rag's vector store handles the embedding and insertion
    vector_store.add_documents(ai4rag_chunks)

    print(f"\n✅ Done! {len(ai4rag_chunks)} chunks inserted into Milvus collection '{milvus_collection}'")
    print("\n📋 To use this collection, update your .env file:")
    print(f"   MILVUS_COLLECTION_NAME={milvus_collection}")

    return milvus_collection


if __name__ == "__main__":
    collection_name = load_and_index_documents()
