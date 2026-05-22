"""Shared fixtures for evalhub_adapter tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: ensure ``mlflow`` is importable even when it is not installed.
# The adapter imports mlflow lazily inside _log_mlflow_run, but test patches
# like @patch("mlflow.log_metric") need the module in sys.modules at
# decoration time.  .[test] alone does NOT install mlflow (it lives in the
# test-mlflow extra).
# ---------------------------------------------------------------------------
if "mlflow" not in sys.modules:
    _need_mlflow_stub = True
    try:
        import importlib.util as _ilu

        _need_mlflow_stub = _ilu.find_spec("mlflow") is None
    except (ImportError, ValueError):
        pass

    if _need_mlflow_stub:  # pragma: no cover
        _mlflow = ModuleType("mlflow")
        for _fn in (
            "log_metric",
            "log_param",
            "start_run",
            "set_experiment",
            "set_tracking_uri",
            "set_tag",
        ):
            setattr(_mlflow, _fn, lambda *a, **kw: None)
        sys.modules.setdefault("mlflow", _mlflow)


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for YAML-based tests."""
    return tmp_path
