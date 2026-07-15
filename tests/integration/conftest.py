from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def cluster_auth():
    try:
        user = subprocess.run(
            ["oc", "whoami"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        ).stdout.strip()

        namespace = subprocess.run(
            ["oc", "project", "-q"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        ).stdout.strip()
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        pytest.skip("Not logged into an OpenShift cluster")

    if namespace != "ci-testing":
        pytest.fail(
            f"Integration tests must run in ci-testing namespace, got: {namespace}"
        )

    return {"user": user, "namespace": namespace}


@pytest.fixture(scope="session")
def repo_root() -> Path:
    root = Path(__file__).resolve().parent.parent.parent
    assert (root / "agents").is_dir(), f"Repo root not found at {root}"
    return root
