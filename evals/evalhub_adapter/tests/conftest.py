"""Shared fixtures for evalhub_adapter tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: ensure ``evalhub`` is importable even when the real package
# (eval-hub-sdk) is not installed.  Seeding sys.modules with a lightweight
# stub lets the test suite import cleanly.
#
# The stub must match the real SDK's type signatures (Pydantic models, enums)
# closely enough that adapter.py's imports and type usage work in tests.
# ---------------------------------------------------------------------------
if "evalhub" not in sys.modules:
    _need_stub = True
    try:
        import importlib.util

        _need_stub = importlib.util.find_spec("evalhub") is None
    except (ImportError, ValueError):
        pass

    if _need_stub:  # pragma: no cover – only when eval-hub-sdk truly absent
        import enum
        from dataclasses import dataclass, field
        from typing import Any as _Any

        # --- evalhub.models.api stubs ---
        _eh = ModuleType("evalhub")
        _eh_models = ModuleType("evalhub.models")
        _eh_models_api = ModuleType("evalhub.models.api")

        class _JobStatus(enum.Enum):
            PENDING = "pending"
            RUNNING = "running"
            COMPLETED = "completed"
            FAILED = "failed"
            CANCELLED = "cancelled"

        class _ModelConfig:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        @dataclass
        class _EvaluationResult:
            metric_name: str
            metric_value: float
            metric_type: str = "float"
            confidence_interval: tuple[float, float] | None = None
            num_samples: int | None = None
            metadata: dict[str, _Any] = field(default_factory=dict)

        _eh_models_api.JobStatus = _JobStatus  # type: ignore[attr-defined]
        _eh_models_api.ModelConfig = _ModelConfig  # type: ignore[attr-defined]
        _eh_models_api.EvaluationResult = _EvaluationResult  # type: ignore[attr-defined]

        # --- evalhub.adapter stubs ---
        _eh_adapter = ModuleType("evalhub.adapter")

        class _JobPhase(enum.Enum):
            INITIALIZING = "initializing"
            LOADING_DATA = "loading_data"
            RUNNING_EVALUATION = "running_evaluation"
            POST_PROCESSING = "post_processing"
            PERSISTING_ARTIFACTS = "persisting_artifacts"
            COMPLETED = "completed"

        class _FrameworkAdapter:
            def __init__(self, settings=None, job_spec_path=None):
                pass

        class _JobSpec:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

            @classmethod
            def from_file(cls, path):
                return cls()

        class _JobCallbacks:
            pass

        class _JobResults:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        class _JobStatusUpdate:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        class _MessageInfo:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        class _ErrorInfo:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        class _DefaultCallbacks:
            def __init__(self, **kwargs):
                pass

        class _AdapterSettings:
            @classmethod
            def from_env(cls):
                return cls()

        _eh_adapter.FrameworkAdapter = _FrameworkAdapter  # type: ignore[attr-defined]
        _eh_adapter.JobSpec = _JobSpec  # type: ignore[attr-defined]
        _eh_adapter.JobCallbacks = _JobCallbacks  # type: ignore[attr-defined]
        _eh_adapter.JobResults = _JobResults  # type: ignore[attr-defined]
        _eh_adapter.JobStatus = _JobStatus  # type: ignore[attr-defined]
        _eh_adapter.JobPhase = _JobPhase  # type: ignore[attr-defined]
        _eh_adapter.JobStatusUpdate = _JobStatusUpdate  # type: ignore[attr-defined]
        _eh_adapter.MessageInfo = _MessageInfo  # type: ignore[attr-defined]
        _eh_adapter.ErrorInfo = _ErrorInfo  # type: ignore[attr-defined]
        _eh_adapter.EvaluationResult = _EvaluationResult  # type: ignore[attr-defined]
        _eh_adapter.DefaultCallbacks = _DefaultCallbacks  # type: ignore[attr-defined]
        _eh_adapter.AdapterSettings = _AdapterSettings  # type: ignore[attr-defined]

        _eh.adapter = _eh_adapter  # type: ignore[attr-defined]
        _eh.models = _eh_models  # type: ignore[attr-defined]
        sys.modules.setdefault("evalhub", _eh)
        sys.modules.setdefault("evalhub.models", _eh_models)
        sys.modules.setdefault("evalhub.models.api", _eh_models_api)
        sys.modules.setdefault("evalhub.adapter", _eh_adapter)


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
