"""Exercise the real installer, curl retries, checksum check, and extraction."""

import hashlib
import http.server
import io
import os
import shutil
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "install_lychee.sh"


@pytest.fixture
def download_server(tmp_path):
    archive = io.BytesIO()
    body = b"#!/bin/sh\necho 'lychee 0.24.2'\n"
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        item = tarfile.TarInfo("lychee-x86_64-unknown-linux-gnu/lychee")
        item.size = len(body)
        item.mode = 0o755
        tar.addfile(item, io.BytesIO(body))
    payload = archive.getvalue()
    state = {"statuses": [200], "requests": 0, "payload": payload}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"] += 1
            statuses = state["statuses"]
            status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
            self.send_response(status)
            self.end_headers()
            self.wfile.write(payload if status == 200 else b"download unavailable")

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Redirect only the external HTTPS transport to our controlled local server.
    # The installed script, curl retry implementation, hash, and tar stay real.
    curl = tmp_path / "curl"
    curl.write_text(
        f"#!{sys.executable}\nimport os,sys\n"
        "args=sys.argv[1:]\n"
        "assert args[-1] == 'https://github.com/lycheeverse/lychee/releases/"
        "download/lychee-v0.24.2/lychee-x86_64-unknown-linux-gnu.tar.gz'\n"
        f"args[-1]='http://127.0.0.1:{server.server_port}/archive'\n"
        f"os.execv({shutil.which('curl')!r}, ['curl', *args])\n"
    )
    curl.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_PATH": str(tmp_path / "github-path"),
    }
    try:
        yield state, env, hashlib.sha256(payload).hexdigest()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def install(tmp_path, env, digest):
    return subprocess.run(
        ["bash", str(INSTALLER), "v0.24.2", digest, str(tmp_path / "bin")],
        capture_output=True,
        text=True,
        env=env,
        timeout=45,
    )


def test_transient_download_recovers_and_installs_verified_binary(
    tmp_path, download_server
):
    state, env, digest = download_server
    state["statuses"] = [503, 200]
    result = install(tmp_path, env, digest)
    assert result.returncode == 0, result.stderr
    assert state["requests"] == 2
    binary = tmp_path / "bin" / "lychee"
    assert (
        subprocess.check_output([str(binary), "--version"], text=True).strip()
        == "lychee 0.24.2"
    )
    assert (tmp_path / "github-path").read_text().strip() == str(tmp_path / "bin")


@pytest.mark.parametrize("status,attempts", [(404, 1), (503, 4)])
def test_download_failure_is_bounded_and_never_installs(
    tmp_path, download_server, status, attempts
):
    state, env, digest = download_server
    state["statuses"] = [status]
    result = install(tmp_path, env, digest)
    assert result.returncode != 0
    assert state["requests"] == attempts
    assert str(status) in result.stderr
    assert not (tmp_path / "bin" / "lychee").exists()
    assert not (tmp_path / "github-path").exists()


def test_checksum_mismatch_never_installs(tmp_path, download_server):
    _state, env, _digest = download_server
    result = install(tmp_path, env, "0" * 64)
    assert result.returncode != 0
    assert "checksum" in result.stderr.lower()
    assert not (tmp_path / "bin" / "lychee").exists()
    assert not (tmp_path / "github-path").exists()
