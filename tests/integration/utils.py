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


def resolve_agent_dir(test_file: str | Path) -> Path:
    test_path = Path(test_file).resolve()
    agent_dir = test_path.parents[2]
    agent_config = agent_dir / "agent.yaml"
    if not agent_config.is_file():
        raise FileNotFoundError(
            f"Could not find agent.yaml from test file {test_path}; "
            f"expected {agent_config}"
        )
    return agent_dir


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
    re.compile(r"(VECTOR_STORE_ID=)\S+"),
    re.compile(r'(--set\s+env\.VECTOR_STORE_ID=")[^"]*"'),
    re.compile(r"(--set\s+env\.VECTOR_STORE_ID=)\S+"),
]


def _redact(text: str | bytes) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
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


def _run_oc_command(
    args: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["oc", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"oc {' '.join(args)} failed ({result.returncode})\n"
            f"stdout: {_redact(result.stdout)}\n"
            f"stderr: {_redact(result.stderr)}"
        )
    return result


def create_serviceaccount(name: str, namespace: str) -> None:
    result = _run_oc_command(
        ["create", "serviceaccount", name, "-n", namespace],
        timeout=30,
        check=False,
    )
    if result.returncode == 0:
        return
    stderr = result.stderr.lower()
    if "alreadyexists" in stderr or "already exists" in stderr:
        return
    raise RuntimeError(
        f"Failed to create service account {namespace}/{name}\n"
        f"stdout: {_redact(result.stdout)}\n"
        f"stderr: {_redact(result.stderr)}"
    )


def delete_serviceaccount(name: str, namespace: str) -> None:
    _run_oc_command(
        ["delete", "serviceaccount", name, "-n", namespace, "--ignore-not-found=true"],
        timeout=30,
        check=True,
    )


def create_sa_token(
    service_account: str,
    namespace: str | None = None,
    audience: str = "langgraph-react-agent",
    duration: str = "15m",
) -> str:
    """Create a short-lived SA token via `oc create token`."""
    cmd = [
        "create",
        "token",
        service_account,
        f"--audience={audience}",
        f"--duration={duration}",
    ]
    if namespace:
        cmd.extend(["-n", namespace])
    result = _run_oc_command(cmd, timeout=30, check=True)
    return result.stdout.strip()


def chat_completion_request(
    base_url: str,
    messages: list[dict[str, str]],
    *,
    headers: dict[str, str] | None = None,
    verify_tls: bool = False,
    timeout: float = 60.0,
) -> httpx.Response:
    with httpx.Client(verify=verify_tls, timeout=timeout) as client:
        return client.post(
            f"{base_url}/chat/completions",
            json={"messages": messages},
            headers=headers,
        )


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
