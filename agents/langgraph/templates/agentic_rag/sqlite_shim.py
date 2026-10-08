"""
Patch sqlite3 to use pysqlite3-binary if available.

Required for chromadb (used by ai4rag) when the system sqlite3 is too old.
Must be called BEFORE importing any code that uses sqlite3.
"""

import sys


def patch_sqlite3() -> None:
    """Replace sys.modules['sqlite3'] with pysqlite3 if available."""
    try:
        import pysqlite3  # noqa: F401

        sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
    except ImportError:
        pass
