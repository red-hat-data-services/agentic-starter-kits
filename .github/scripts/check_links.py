#!/usr/bin/env python3
"""Run lychee without treating documented access failures as verified links."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
# RHAIENG-7920: browser-verified on 2026-11-09. These statuses cannot
# establish whether the requested document exists. All URLs are still checked.
BLOCKED_DOCS_HOSTS = {"docs.redhat.com", "docs.openshift.com"}


@dataclass(frozen=True)
class Finding:
    source: str
    line: int
    url: str
    reason: str
    severity: str


def evaluate_report(report: dict, exit_code: int) -> list[Finding]:
    """Fail closed on checker/schema errors; classify only explicit statuses."""
    if exit_code not in (0, 2) or not isinstance(report, dict):
        raise ValueError(
            f"Lychee failed (exit {exit_code}); link results are incomplete"
        )
    for key in (
        "total",
        "successful",
        "errors",
        "timeouts",
        "unknown",
        "unsupported",
        "excludes",
    ):
        if type(report.get(key)) is not int or report[key] < 0:
            raise ValueError(f"Invalid lychee report counter: {key}")
    if report["unknown"] or report["unsupported"]:
        raise ValueError("Lychee reported unknown or unsupported links")
    accounted = sum(
        report[key]
        for key in (
            "successful",
            "errors",
            "timeouts",
            "unknown",
            "unsupported",
            "excludes",
        )
    )
    if accounted != report["total"]:
        raise ValueError("Incomplete lychee report: results do not account for total")

    findings = []
    for map_name, counter in (("error_map", "errors"), ("timeout_map", "timeouts")):
        entries = report.get(map_name)
        if not isinstance(entries, dict):
            raise ValueError(f"Invalid lychee report: {map_name}")
        count = 0
        for source, results in entries.items():
            if not isinstance(source, str) or not isinstance(results, list):
                raise ValueError(f"Invalid lychee report entries: {map_name}")
            for result in results:
                if not isinstance(result, dict) or not isinstance(
                    result.get("url"), str
                ):
                    raise ValueError("Invalid lychee response URL")
                status = result.get("status")
                if not isinstance(status, dict) or not isinstance(
                    status.get("text"), str
                ):
                    raise ValueError("Invalid lychee response status")
                code = status.get("code")
                if code is not None and (
                    type(code) is not int or not 100 <= code <= 599
                ):
                    raise ValueError("Invalid lychee HTTP status code")
                span = result.get("span") or {}
                line = span.get("line", 1)
                if type(line) is not int or line < 1:
                    raise ValueError("Invalid lychee source line")
                url = result["url"]
                parsed = urlsplit(url)
                unverified = (
                    map_name == "error_map"
                    and parsed.scheme in ("http", "https")
                    and (
                        code == 429
                        or (
                            parsed.hostname in BLOCKED_DOCS_HOSTS and code in (403, 503)
                        )
                    )
                )
                reason = status["text"]
                if code is not None:
                    reason = f"HTTP {code}: {reason}"
                findings.append(
                    Finding(
                        source, line, url, reason, "warning" if unverified else "error"
                    )
                )
                count += 1
        if count != report[counter]:
            raise ValueError(
                f"Incomplete lychee report: {counter} does not match {map_name}"
            )
    if (exit_code == 2) != bool(findings):
        raise ValueError("Lychee exit status disagrees with its report")
    return findings


def pr_files(repository: str, number: int) -> list[str]:
    """Read paginated structured paths, retaining fatal discovery errors."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or number < 1:
        raise ValueError("A valid repository and positive PR number are required")
    result = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repository}/pulls/{number}/files",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    pages = json.loads(result.stdout)
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ValueError("Invalid GitHub changed-files response")
    selected = []
    for page in pages:
        for item in page:
            path = item["filename"]
            if (
                item["status"] != "removed"
                and path.endswith(".md")
                and Path(path).is_file()
            ):
                selected.append(path)
    return selected


def annotation(severity: str, message: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::{severity}::{escaped}")
    else:
        print(f"{severity.upper()}: {message}")


def render_summary(report: dict, findings: list[Finding]) -> str:
    errors = sum(f.severity == "error" for f in findings)
    warnings = len(findings) - errors
    summary = (
        "## Link check\n\n"
        f"{report['total']} checked; {report['successful']} successful; "
        f"{errors} blocking; {warnings} unverified; {report['excludes']} excluded.\n\n"
    )
    if warnings:
        summary += (
            "Unverified links could not be checked because of access blocking or rate limits. "
            "They are **not verified successes**. See `docs/link-check-triage.md`.\n\n"
        )
    for finding in findings:
        label = "Unverified" if finding.severity == "warning" else "Blocking"
        source = html.escape(f"{finding.source}:{finding.line}")
        summary += (
            f"- **{label}** <code>{source}</code>: "
            f"<code>{html.escape(finding.url)}</code> — {html.escape(finding.reason)}\n"
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="Check all tracked Markdown")
    mode.add_argument(
        "--pr", type=int, help="Check existing Markdown changed in this PR"
    )
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--config", type=Path, default=ROOT / "lychee.toml")
    parser.add_argument(
        "--report-dir", type=Path, help="Persist results.json and summary.md"
    )
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()
    if (args.all or args.pr is not None) and args.files:
        parser.error("Use either a discovery mode or explicit files")
    if not args.all and args.pr is None and not args.files:
        parser.error("Specify --all, --pr, or files")

    try:
        if args.pr is not None:
            targets = pr_files(args.repository, args.pr)
        elif args.all:
            result = subprocess.run(
                ["git", "ls-files", "-z", "--", "*.md"],
                check=True,
                capture_output=True,
                text=True,
            )
            targets = [
                path
                for path in result.stdout.split("\0")
                if path and Path(path).is_file()
            ]
        else:
            targets = args.files
        if not targets:
            print("No existing Markdown files selected; skipping link check")
            return 0
        with tempfile.TemporaryDirectory(prefix="link-check-") as temp:
            output_dir = args.report_dir or Path(temp)
            output_dir.mkdir(parents=True, exist_ok=True)
            output = output_dir / "results.json"
            # Never consume a previous successful report after a setup/CLI failure.
            output.unlink(missing_ok=True)
            result = subprocess.run(
                [
                    "lychee",
                    "--config",
                    str(args.config),
                    "--no-progress",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                    "--",
                    *targets,
                ],
                check=False,
            )
            report = json.loads(output.read_text())
            findings = evaluate_report(report, result.returncode)
            summary = render_summary(report, findings)
            (output_dir / "summary.md").write_text(summary)
            if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
                with Path(summary_file).open("a") as stream:
                    stream.write(summary)
            for finding in findings:
                prefix = (
                    "Unverified" if finding.severity == "warning" else "Broken link"
                )
                annotation(
                    finding.severity,
                    f"{prefix}: {finding.source}:{finding.line}: {finding.url} ({finding.reason})",
                )
            print(summary.splitlines()[2])
            return int(any(f.severity == "error" for f in findings))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.CalledProcessError,
    ) as exc:
        annotation("error", f"Link checker failed; results are incomplete: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
