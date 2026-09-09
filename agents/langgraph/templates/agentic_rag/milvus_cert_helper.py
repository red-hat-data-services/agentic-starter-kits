"""
Helper for MILVUS_SERVER_CERT normalization.

Handles both file paths and PEM text, reading from disk if needed
and updating os.environ for ai4rag's vector store config.
"""

import os


def normalize_milvus_cert() -> None:
    """
    Normalize MILVUS_SERVER_CERT to PEM text in os.environ.

    If MILVUS_SERVER_CERT is set and looks like a file path (doesn't start with
    -----BEGIN), reads the certificate content from disk and updates os.environ.
    If it's already PEM text, leaves it unchanged.
    If not set or empty, does nothing.

    Raises:
        FileNotFoundError: if cert path is provided but file doesn't exist
    """
    milvus_cert = os.getenv("MILVUS_SERVER_CERT")
    if not milvus_cert:
        return

    # Already PEM text
    if milvus_cert.startswith("-----BEGIN"):
        return

    # It's a file path - read the certificate content
    if not os.path.exists(milvus_cert):
        raise FileNotFoundError(f"MILVUS_SERVER_CERT file not found at {milvus_cert}")

    with open(milvus_cert, "r") as f:
        cert_content = f.read()

    os.environ["MILVUS_SERVER_CERT"] = cert_content
