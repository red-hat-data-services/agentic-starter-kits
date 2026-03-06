"""
Script to load documents from text files into a vector store via LlamaStack.

If VECTOR_STORE_ID is set, documents are added to the existing store.
Otherwise, a new vector store is created using VECTOR_STORE_NAME,
its ID is printed and written back into the .env file.
"""

import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from llama_stack_client import LlamaStackClient

from os import getenv

load_dotenv(verbose=True)


def update_env_file(key: str, value: str):
    """Update or add a key=value pair in the .env file next to this script."""
    env_path = (
        Path(__file__).resolve().parent.parent / ".env"
    )  # data/ -> langgraph_agentic_rag/.env
    if not env_path.exists():
        env_path.write_text(f"{key}={value}\n")
        return

    lines = env_path.read_text().splitlines()
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped == key:
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n")


def load_and_index_documents(
    docs_to_load: str = None,
    embedding_model: str = None,
    base_url: str = None,
    api_key: str = None,
    chunk_size: int = 512,
    chunk_overlap: int = 128,
):
    """
    Load documents from directory and index them in a vector store.

    Args:
        docs_to_load: Directory containing text files to load
        embedding_model: Name of the embedding model
        base_url: Base URL for embeddings API
        api_key: API key for embeddings
        chunk_size: Size of text chunks
        chunk_overlap: Overlap between chunks
    """
    if not embedding_model:
        embedding_model = getenv("EMBEDDING_MODEL")

    if not base_url:
        base_url = getenv("BASE_URL")

    if not api_key:
        api_key = getenv("API_KEY") or "not-needed"

    if not docs_to_load:
        docs_to_load = getenv("DOCS_TO_LOAD")

    client = LlamaStackClient(
        base_url=base_url,
        api_key=api_key,
    )

    vector_store_id = getenv("VECTOR_STORE_ID")
    provider_id = "milvus"
    embedding_dimension = 768

    if vector_store_id:
        # Use existing vector store
        print(f"Using existing vector store: {vector_store_id}")
    else:
        # Create a new vector store
        vector_store = client.vector_stores.create(
            extra_body={
                "provider_id": provider_id,
                "embedding_model": embedding_model,
                "embedding_dimension": embedding_dimension,
            },
        )
        vector_store_id = vector_store.id
        print(f"Vector store created: id={vector_store_id} name={vector_store.name}")

        # Persist the new ID to .env
        update_env_file("VECTOR_STORE_ID", vector_store_id)
        print(f"Updated .env with VECTOR_STORE_ID={vector_store_id}")
        print("NOTE!: Please use `source ./init.sh' to update the env variables.")

    print("Loading documents from directory...")
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
            chunks.append(content)
    print(f"Created {len(chunks)} chunks (filtered out empty/separator chunks)")

    print("\nInitializing embeddings...")
    embeddings = OpenAIEmbeddings(
        model=embedding_model,
        api_key=api_key or "not-needed",
        base_url=base_url + "/v1",
        check_embedding_ctx_length=False,  # prevent fail if embedding model is not registered in OpenAI Registry
    )

    print("Creating embeddings...")
    embedding_vectors = embeddings.embed_documents(texts=chunks)

    print("Formatting chunks...")
    formatted_chunks = []
    for i, (text, embedding_vec) in enumerate(zip(chunks, embedding_vectors)):
        chunk = {
            "chunk_id": str(uuid.uuid4()),
            "content": text,
            "embedding": embedding_vec,
            "embedding_dimension": 768,
            "embedding_model": embedding_model,
            "chunk_metadata": {
                "document_id": "doc_1",
                "source": "sample_knowledge.txt",
            },
            "metadata": {
                "chunk_index": i,
            },
        }
        formatted_chunks.append(chunk)

    print("\nLoading chunks to Vector Store...")
    client.vector_io.insert(
        chunks=formatted_chunks,
        vector_store_id=vector_store_id,
    )

    print(
        f"Done! {len(formatted_chunks)} chunks inserted into vector store {vector_store_id}"
    )


if __name__ == "__main__":
    load_and_index_documents()
