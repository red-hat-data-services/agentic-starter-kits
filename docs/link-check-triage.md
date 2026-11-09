# Link-check failures and unavailable sites

Code Quality and pre-commit both run `.github/scripts/check_links.py`, which
invokes lychee and evaluates its JSON report. All selected links are still
requested. Access failures are reported as **unverified**, never as successful
checks or silently skipped links.

## Policy

- Missing local files, HTTP 404/410, malformed URLs, timeouts, and other failures
  block the check.
- HTTP 429 on an HTTP(S) URL is an unverified warning: the server rate-limited
  the request, so the link's existence is unknown.
- HTTP 403/503 on exactly `docs.redhat.com` or `docs.openshift.com` is an
  unverified warning. These hosts have returned those statuses for valid pages
  from automated clients. Browser checks on November 9, 2026 confirmed that the
  CLI getting-started and image-pull-secret sections, and the OpenShift docs
  landing page, load for users while the configured curl user agent gets 403.
- HTTP 404/410 on those same hosts still blocks. A 403/503 from any other host
  still blocks and must be investigated before changing the policy.
- Missing or malformed reports, unexpected lychee exit codes, incomplete result
  counts, and file-discovery failures block. A failed checker is not a clean scan.

The summary lists successful, blocking, unverified, and excluded counts separately,
with each failed or unverified URL and its source location. Existing narrow
exclusions in `lychee.toml` remain excluded, and are not verified successes.
HTTP 403/503 are never globally accepted. Neither Red Hat documentation host is
excluded. Unknown/unsupported result types fail closed if lychee changes format.

## Run locally

Install lychee 0.24.2 using your platform's package tooling, and use Python 3.12
or newer. The wrapper has no third-party Python dependencies.

```bash
# Check specific files, including new/untracked Markdown.
python3 .github/scripts/check_links.py README.md docs/openshift-deployment.md

# Check all tracked Markdown, with JSON and Markdown reports outside the repo.
python3 .github/scripts/check_links.py --all --report-dir /tmp/link-check

# Reproduce a PR's selection; requires authenticated gh access.
python3 .github/scripts/check_links.py --repository red-hat-data-services/agentic-starter-kits --pr 401
```

Running lychee directly applies its strict raw status behavior without the
availability policy. Use the wrapper to reproduce CI/pre-commit outcomes.

PR runs check existing added/modified/renamed Markdown using the paginated GitHub
files API. Deleted files are skipped. Filenames are passed as subprocess arguments,
not shell commands. Main and manual runs check all tracked Markdown. A green PR
scan is not a complete repository audit.

## Triage

1. Open the Actions job summary and distinguish blocking links, unverified
   responses, and checker installation failures.
2. For a blocking link, verify the intended page and section in a real browser.
   Check the response and redirect destination with
   `curl -L -A 'curl/8.7.1' -o /dev/null -w '%{http_code} %{url_effective}\n' URL`.
   A login page or generic documentation home is not a valid replacement for a
   specific missing document.
3. Fix genuine broken URLs and local paths. Preserve intentional version pins;
   do not mechanically change hostnames across different documentation layouts.
4. For unverified links, browser-check new or edited URLs before merging. The
   warning means existence could not be established, so it can also conceal a
   missing page behind an access filter. Leave the warning visible.
5. Before adding a host-specific status rule, record the exact hostname/status,
   date, failed run, and browser evidence. Add regression coverage showing that
   404/410 on that host and failures on other hosts still block. Prefer fixing
   the URL when a real replacement exists. Do not broaden global `accept` codes.

Maintainers should review the host/status rules during recurring CI maintenance
and after documentation platform changes. Remove a rule after valid pages work
from actual GitHub runners without it; until then the scan continues requesting
every URL and surfacing access failures. This is an explicit coverage limitation,
not proof that every unverified link is valid.

## Installation failures

CI installs the same pinned lychee 0.24.2 Linux x86_64 binary with a committed
SHA256. Its downloader retries transient curl/HTTP failures three times after the
initial attempt, with a bounded retry window and request timeouts. A permanent
HTTP 404, exhausted retry budget, or checksum mismatch fails before scanning.
The actual curl error remains in the log. Do not retry the entire link check or
reuse an earlier report to turn an installation failure green.

When changing the version, update the version and trusted release checksum in
`.github/workflows/code-quality.yml` together, and verify report compatibility.
The wrapper is also used by pre-commit, so policy changes apply consistently.

## Related work

- [RHAIENG-7919](https://redhat.atlassian.net/browse/RHAIENG-7919) fixed real URLs
  broken by the Red Hat docs migration in
  [PR #387](https://github.com/red-hat-data-services/agentic-starter-kits/pull/387).
  Keep those replacements.
- [RHAIENG-7920](https://redhat.atlassian.net/browse/RHAIENG-7920) tracks resilient
  bot-block triage. Its historical inventory is stale: the November 9 main
  snapshot has no `docs.openshift.com/container-platform` links left. This policy
  supersedes the proposal to globally accept HTTP 503.
- [PR #401's rerun](https://github.com/red-hat-data-services/agentic-starter-kits/actions/runs/42270962650/job/129283674363)
  reproduced six 403 failures from three browser-accessible URLs.
- [Main's full scan](https://github.com/red-hat-data-services/agentic-starter-kits/actions/runs/42642292775/job/129246253367)
  reported 35 403 failures across ten unique URLs.
