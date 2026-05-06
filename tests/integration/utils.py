from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path

import httpx
import yaml

logger = logging.getLogger(__name__)


def load_agent_name(agent_dir: str | Path) -> str:
    data = yaml.safe_load((Path(agent_dir) / "agent.yaml").read_text())
    if not isinstance(data, dict) or "name" not in data:
        raise ValueError(f"No 'name' field in {agent_dir}/agent.yaml")
    return str(data["name"]).strip()


_REDACT_PATTERNS = [
    re.compile(r"(API_KEY=)\S+"),
    re.compile(r'(apiKey:\s*")[^"]*"'),
    re.compile(r'(--set\s+secrets\.apiKey=")[^"]*"'),
    re.compile(r"(--set\s+secrets\.apiKey=)\S+"),
]


def _redact(text: str) -> str:
    for pattern in _REDACT_PATTERNS:
        text = pattern.sub(r"\1***REDACTED***", text)
    return text


class MakeTargetError(Exception):
    def __init__(self, target: str, returncode: int, stdout: str, stderr: str):
        self.target = target
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"make {target} failed (exit {returncode})\n"
            f"--- stdout ---\n{_redact(stdout)}\n"
            f"--- stderr ---\n{_redact(stderr)}"
        )


class RouteNotFoundError(Exception):
    def __init__(self, agent_name: str, stderr: str = ""):
        self.agent_name = agent_name
        self.stderr = stderr
        detail = f"\noc stderr: {stderr}" if stderr else ""
        super().__init__(f"No route found for {agent_name}{detail}")


class HealthCheckError(Exception):
    def __init__(self, url: str, attempts: int):
        self.url = url
        self.attempts = attempts
        super().__init__(f"Health check failed after {attempts} attempts: {url}")


def run_make(
    target: str,
    cwd: str | Path,
    timeout: int = 300,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    try:
        result = subprocess.run(
            ["make", target],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=merged_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise MakeTargetError(
            target,
            returncode=-1,
            stdout=exc.stdout or "",
            stderr=f"Timed out after {timeout}s",
        ) from exc

    if result.returncode != 0:
        raise MakeTargetError(target, result.returncode, result.stdout, result.stderr)

    return result


def get_route(agent_name: str, namespace: str | None = None) -> str:
    cmd = [
        "oc",
        "get",
        "route",
        agent_name,
        "-o",
        "jsonpath={.spec.host}",
    ]
    if namespace:
        cmd.extend(["-n", namespace])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    host = result.stdout.strip()

    if result.returncode != 0 or not host:
        raise RouteNotFoundError(agent_name, stderr=result.stderr.strip())

    return f"https://{host}"


def health_check(
    url: str,
    retries: int = 12,
    backoff: float = 5.0,
    verify_tls: bool = False,
) -> dict:
    last_exc: Exception | None = None

    with httpx.Client(verify=verify_tls, timeout=10.0) as client:
        for attempt in range(retries):
            try:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.json()
            except (
                httpx.HTTPStatusError,
                httpx.ConnectError,
                httpx.TimeoutException,
            ) as exc:
                last_exc = exc
                if attempt == retries - 1:
                    break
                wait = min(backoff * (2**attempt), 15.0)
                logger.info(
                    "Health check attempt %d/%d failed, retrying in %.1fs: %s",
                    attempt + 1,
                    retries,
                    wait,
                    exc,
                )
                time.sleep(wait)

    raise HealthCheckError(url, retries) from last_exc
