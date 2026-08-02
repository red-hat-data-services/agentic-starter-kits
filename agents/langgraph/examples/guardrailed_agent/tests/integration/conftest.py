"""Re-export shared cluster fixtures from the repo-root integration harness.

Import explicitly from ``tests/integration/conftest.py`` so this agent's local
``tests/integration/`` package cannot shadow the shared ``integration``
namespace when pytest collects tests from here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SHARED_INTEGRATION_CONFTEST = (
    Path(__file__).resolve().parents[6] / "tests" / "integration" / "conftest.py"
)
_spec = importlib.util.spec_from_file_location(
    "repo_integration_conftest",
    _SHARED_INTEGRATION_CONFTEST,
)
if _spec is None or _spec.loader is None:
    raise ImportError(
        f"Cannot load shared integration conftest at {_SHARED_INTEGRATION_CONFTEST}"
    )
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

cluster_auth = _mod.cluster_auth
repo_root = _mod.repo_root

__all__ = ["cluster_auth", "repo_root"]
