#!/usr/bin/env python3
"""
PR Size Labeler — calculates PR size and applies size/* labels.

Triggered by the pr-labeler workflow. Uses the GitHub API via PyGitHub
to count lines changed (additions + deletions), excluding lock files,
generated files, and images. Posts an advisory comment on XL PRs.

Environment variables (set by the workflow):
    GITHUB_TOKEN        — GitHub token with pull-requests: write
    GITHUB_REPOSITORY   — owner/repo
    PR_NUMBER           — pull request number
"""

import fnmatch
import os
import sys

from github import Github
from github.GithubException import GithubException

# --- Configuration ---

SIZE_THRESHOLDS = [
    ("size/xs", 0, 10),
    ("size/s", 11, 100),
    ("size/m", 101, 500),
    ("size/l", 501, 1199),
    ("size/xl", 1200, float("inf")),
]

LABEL_COLORS = {
    "size/xs": "0e8a16",
    "size/s": "0e8a16",
    "size/m": "0e8a16",
    "size/l": "fbca04",
    "size/xl": "d93f0b",
}

EXCLUDED_PATTERNS = [
    "uv.lock",
    "*.lock",
    "*.generated.*",
]

XL_COMMENT_MARKER = "<!-- pr-size-labeler:xl-warning -->"

XL_COMMENT_TEMPLATE = """{marker}
**Large PR detected ({lines} lines changed)**

This PR exceeds 1200 lines of code changes (excluding lock files, \
generated content, and images). Large PRs are harder to review thoroughly \
and are more likely to introduce bugs.

Consider splitting this PR into smaller, focused changes.
"""


def is_excluded(filename: str) -> bool:
    """Check if a file matches any exclusion pattern or is inside an images/ directory."""
    # Check path-component match for images directories at any depth
    if "/images/" in f"/{filename}":
        return True
    for pattern in EXCLUDED_PATTERNS:
        if fnmatch.fnmatch(filename, pattern):
            return True
    return False


def get_size_label(lines: int) -> str:
    """Return the size label for the given line count."""
    for label, lower, upper in SIZE_THRESHOLDS:
        if lower <= lines <= upper:
            return label
    return "size/xl"


def ensure_label_exists(repo, label_name: str) -> None:
    """Create the label in the repo if it doesn't exist."""
    try:
        repo.get_label(label_name)
    except GithubException as exc:
        if exc.status != 404:
            raise
        color = LABEL_COLORS.get(label_name, "ededed")
        repo.create_label(name=label_name, color=color)
        print(f"Created label: {label_name}")


def update_size_label(pr, new_label: str) -> bool:
    """Update the size label on a PR. Returns True if a change was made."""
    found = False
    stale = []
    for label in pr.get_labels():
        if label.name == new_label:
            found = True
        elif label.name.startswith("size/"):
            stale.append(label.name)

    if found and not stale:
        print(f"Label already correct: {new_label}")
        return False

    for name in stale:
        pr.remove_from_labels(name)
        print(f"Removed label: {name}")

    if not found:
        pr.add_to_labels(new_label)
        print(f"Applied label: {new_label}")

    return True


def calculate_size(pr) -> int:
    """Calculate total lines changed, excluding ignored files."""
    total = 0
    for f in pr.get_files():
        if not is_excluded(f.filename):
            total += f.additions + f.deletions
        else:
            print(f"Excluded: {f.filename}")
    return total


def post_xl_comment(pr, lines: int) -> None:
    """Post an XL warning comment if one doesn't already exist."""
    for comment in pr.get_issue_comments():
        if XL_COMMENT_MARKER in comment.body:
            print("XL comment already exists, skipping")
            return
    body = XL_COMMENT_TEMPLATE.format(marker=XL_COMMENT_MARKER, lines=lines)
    pr.create_issue_comment(body)
    print("Posted XL warning comment")


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    pr_number_str = os.environ.get("PR_NUMBER")

    if not all([token, repo_name, pr_number_str]):
        print("Error: GITHUB_TOKEN, GITHUB_REPOSITORY, and PR_NUMBER must be set")
        sys.exit(1)

    pr_number = int(pr_number_str)

    gh = Github(token, retry=3)
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)

    lines = calculate_size(pr)
    label = get_size_label(lines)
    print(f"PR #{pr_number}: {lines} lines changed -> {label}")

    ensure_label_exists(repo, label)
    update_size_label(pr, label)

    if label == "size/xl":
        post_xl_comment(pr, lines)


if __name__ == "__main__":
    main()
