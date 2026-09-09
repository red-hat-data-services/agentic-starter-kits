#!/usr/bin/env python3
"""
Wrapper to fix sqlite3 issue before importing ai4rag.
This MUST be the entry point, not load_documents_ai4rag.py directly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlite_shim import patch_sqlite3

patch_sqlite3()

if __name__ == "__main__":
    from load_documents_ai4rag import load_and_index_documents

    load_and_index_documents()
