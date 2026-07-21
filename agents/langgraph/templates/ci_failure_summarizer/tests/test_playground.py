"""Tests for the Flask playground assets."""

from __future__ import annotations

from pathlib import Path


def test_playground_template_uses_flask_api_routes():
    template = Path(__file__).parent.parent / "playground" / "templates" / "index.html"
    text = template.read_text()

    assert "fetch('/api/health')" in text
    assert "fetch('/api/chat'" in text
    assert "fetch('/health')" not in text
    assert "fetch('/chat/completions'" not in text
