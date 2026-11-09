"""Link-check policy: blocked requests are unverified, broken links still fail."""

import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
SCRIPT = SCRIPTS / "check_links.py"


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location("check_links", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def report_for(url, code=None, *, timeout=False):
    status = {"text": "Request timed out" if timeout else "Request failed"}
    if code is not None:
        status["code"] = code
    issue = {"url": url, "status": status, "span": {"line": 7, "column": 1}}
    return {
        "total": 1,
        "unique": 1,
        "successful": 0,
        "unknown": 0,
        "unsupported": 0,
        "timeouts": int(timeout),
        "redirects": 0,
        "remaps": 0,
        "excludes": 0,
        "errors": int(not timeout),
        "cached": 0,
        "success_map": {},
        "error_map": {} if timeout else {"docs/example.md": [issue]},
        "timeout_map": {"docs/example.md": [issue]} if timeout else {},
        "suggestion_map": {},
        "redirect_map": {},
        "excluded_map": {},
        "duration": {"secs": 1, "nanos": 0},
        "detailed_stats": False,
    }


@pytest.mark.parametrize(
    ("url", "code", "expected"),
    [
        ("https://docs.redhat.com/en/example", 403, "warning"),
        ("https://docs.redhat.com/en/example", 503, "warning"),
        ("https://docs.openshift.com/", 403, "warning"),
        ("https://docs.openshift.com/", 503, "warning"),
        ("https://docs.vllm.ai/en/example", 429, "warning"),
        ("https://docs.redhat.com/en/missing", 404, "error"),
        ("https://docs.redhat.com/en/gone", 410, "error"),
        ("https://docs.openshift.com/missing", 404, "error"),
        ("https://another.example/blocked", 403, "error"),
        ("https://another.example/unavailable", 503, "error"),
        ("https://docs.redhat.com.example.org/", 403, "error"),
        ("https://docs.redhat.com@another.example/", 403, "error"),
        ("file:///tmp/missing.md", None, "error"),
    ],
)
def test_policy_keeps_real_failures_blocking(checker, url, code, expected):
    findings = checker.evaluate_report(report_for(url, code), 2)
    assert len(findings) == 1
    assert findings[0].severity == expected
    assert findings[0].url == url
    assert findings[0].source == "docs/example.md"
    assert findings[0].line == 7


def test_timeout_is_not_silently_accepted(checker):
    findings = checker.evaluate_report(
        report_for("https://docs.redhat.com/en/example", timeout=True), 2
    )
    assert findings[0].severity == "error"


@pytest.mark.parametrize("exit_code", [1, 3, 127, -9])
def test_checker_failures_are_not_demoted(checker, exit_code):
    with pytest.raises(ValueError):
        checker.evaluate_report(report_for("https://docs.redhat.com/", 403), exit_code)


@pytest.mark.parametrize(
    "change",
    [
        {"total": 100},
        {"successful": 10},
        {"error_map": {}},
        {"errors": 0},
        {"errors": True},
        {"unknown": 1},
        {"unsupported": 1},
        {"error_map": {"example.md": [{"url": "https://docs.redhat.com/"}]}},
        {"timeouts": 1},
    ],
)
def test_incomplete_reports_fail_closed(checker, change):
    report = report_for("https://docs.redhat.com/", 403)
    report.update(change)
    with pytest.raises(ValueError):
        checker.evaluate_report(report, 2)


def run_with_report(tmp_path, report, exit_code=2):
    """Fake only the external checker process, preserving our real CLI/reporting."""
    binary = tmp_path / "lychee"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "assert args[-1] == 'docs/space name.md', args\n"
        f"payload = {json.dumps(report)!r}\n"
        "pathlib.Path(args[args.index('--output') + 1]).write_text(payload)\n"
        f"sys.exit({exit_code})\n"
    )
    binary.chmod(0o755)
    summary = tmp_path / "summary.md"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_ACTIONS": "true",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--report-dir",
            str(tmp_path / "reports"),
            "docs/space name.md",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    return result, summary


def test_cli_surfaces_unverified_links_without_failing(tmp_path):
    result, summary = run_with_report(
        tmp_path, report_for("https://docs.redhat.com/en/example", 403)
    )
    assert result.returncode == 0, result.stderr
    assert "::warning" in result.stdout
    assert "unverified" in summary.read_text().lower()
    assert "https://docs.redhat.com/en/example" in summary.read_text()
    assert "docs/example.md:7" in summary.read_text()
    assert (tmp_path / "reports" / "results.json").exists()


def test_cli_mixed_blocked_and_broken_links_fails(tmp_path):
    report = report_for("https://docs.redhat.com/en/example", 403)
    report["error_map"]["docs/example.md"].append(
        {
            "url": "https://docs.redhat.com/en/missing",
            "status": {"code": 404, "text": "Not found"},
            "span": {"line": 8, "column": 1},
        }
    )
    report.update(total=2, unique=2, errors=2)
    result, summary = run_with_report(tmp_path, report)
    assert result.returncode == 1
    assert "::error" in result.stdout
    assert "1 blocking" in summary.read_text()
    assert "1 unverified" in summary.read_text()


def test_cli_malformed_json_fails_instead_of_reporting_success(tmp_path):
    binary = tmp_path / "lychee"
    binary.write_text(f"#!{sys.executable}\nprint('not a report')\n")
    binary.chmod(0o755)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "docs/example.md"],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
    )
    assert result.returncode == 1


def test_summary_does_not_render_untrusted_html(tmp_path):
    result, summary = run_with_report(
        tmp_path,
        report_for("https://docs.redhat.com/<img src=x onerror=alert(1)>", 403),
    )
    assert result.returncode == 0
    assert "<img" not in summary.read_text()
    assert "&lt;img" in summary.read_text()


def test_pr_selection_uses_json_and_preserves_spaces(checker, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "space name.md").write_text("docs")
    (tmp_path / "README.md").write_text("docs")
    (tmp_path / "code.py").write_text("pass")
    gh = tmp_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        "assert sys.argv[1:] == ['api', '--paginate', '--slurp', "
        "'repos/example/repo/pulls/401/files']\n"
        "print(json.dumps([[{'filename':'space name.md','status':'modified'}, "
        "{'filename':'deleted.md','status':'removed'}], "
        "[{'filename':'README.md','status':'added'}, "
        "{'filename':'code.py','status':'modified'}]]))\n"
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    assert checker.pr_files("example/repo", 401) == ["space name.md", "README.md"]


def test_pr_discovery_failure_is_fatal(checker, tmp_path, monkeypatch):
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\nexit 1\n")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(subprocess.CalledProcessError):
        checker.pr_files("example/repo", 401)


def test_precommit_leading_dash_filename_cannot_override_config(tmp_path):
    root = SCRIPTS.parents[1]
    config = yaml.safe_load((root / ".pre-commit-config.yaml").read_text())
    hook = next(h for r in config["repos"] for h in r["hooks"] if h["id"] == "lychee")
    binary = tmp_path / "lychee"
    recorded_args = tmp_path / "arguments.json"
    binary.write_text(
        f"#!{sys.executable}\nimport json,pathlib,sys\n"
        "args=sys.argv[1:]\n"
        f"pathlib.Path({str(recorded_args)!r}).write_text(json.dumps(args))\n"
        f"payload={json.dumps(report_for('https://docs.redhat.com/', 403))!r}\n"
        "pathlib.Path(args[args.index('--output')+1]).write_text(payload)\n"
        "sys.exit(2)\n"
    )
    binary.chmod(0o755)
    result = subprocess.run(
        [
            *shlex.split(hook["entry"]),
            *hook.get("args", []),
            "--config=permissive.md",
            "docs/example.md",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    arguments = json.loads(recorded_args.read_text())
    assert arguments[arguments.index("--config") + 1] == str(root / "lychee.toml")
    assert arguments[-2:] == ["--config=permissive.md", "docs/example.md"]
