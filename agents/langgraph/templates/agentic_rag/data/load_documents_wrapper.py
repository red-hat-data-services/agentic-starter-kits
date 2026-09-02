#!/usr/bin/env python3
"""
Wrapper to fix sqlite3 issue before importing ai4rag.
This MUST be the entry point, not load_documents_ai4rag.py directly.
"""

import sys

# CRITICAL: Do this BEFORE any other imports
try:
    import pysqlite3

    sys.modules["sqlite3"] = pysqlite3
    print("✓ Using pysqlite3 instead of system sqlite3")
except ImportError:
    print("⚠ pysqlite3-binary not found, using system sqlite3")

# Now it's safe to import and run the actual loader
if __name__ == "__main__":
    from load_documents_ai4rag import load_and_index_documents

    load_and_index_documents()
