"""Tests for deploy-time helper scripts in the template Makefile."""

from __future__ import annotations

import re
from pathlib import Path


def _deploy_inline_python_script() -> str:
    makefile = Path(__file__).parent.parent / "Makefile"
    text = makefile.read_text()
    match = re.search(r"python3 -c '(?P<script>.*?)' && \\\n", text, re.DOTALL)
    assert match is not None
    return match.group("script")


def test_deploy_inline_python_script_compiles():
    script = _deploy_inline_python_script()

    compile(script, "<deploy-inline-python>", "exec")
