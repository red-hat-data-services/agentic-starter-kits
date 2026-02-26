# Contributing to Agentic starter kits

Thank you for your interest in contributing. This document gives a short overview of how to get involved.

## How to contribute

- **Report bugs or suggest features** – Open an [issue](https://github.com/red-hat-data-services/agentic-starter-kits/issues) and describe the problem or idea. Check existing issues first to avoid duplicates.

- **Submit code changes** – Create a branch (in your fork or directly in this repo if you have access), make your changes, and open a pull request (PR). You don’t need to fork if you can push branches here. Keep PRs focused; one feature or fix per PR is easier to review.

- **Improve documentation** – Fixes and clarifications in the README, agent docs, or code comments are always welcome. Use the `docs:` prefix in your commit (see below).

- **Add or fix tests** – If you add or change behavior, consider adding or updating tests and use the `test:` prefix in commits.

Before submitting, please read our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it.

## Commit message conventions

We encourage [Conventional Commits](https://www.conventionalcommits.org/) so that history and release notes stay clear.

Use one of these prefixes at the start of your commit message:

| Prefix    | Meaning |
| --------- | -------- |
| **feat:** | A new feature |
| **fix:**  | A bug fix |
| **perf:** | A change that improves performance |
| **chore:**| Maintenance (deps, tooling, config) |
| **docs:** | Documentation only |
| **test:** | Adding or updating tests |

You can optionally add a scope (e.g. the agent or module name) in parentheses after the type.

### Examples

```
feat: add health check endpoint to autogen_agent
fix: correct env var name in deployment in langgraph_react_agent
docs: update README with OpenShift deploy steps
test: add tests for tool registration
chore: bump python-dotenv in requirements
```

This is optional but appreciated; maintainers may ask you to reword commits when preparing a release.

## Questions?

See the main [README](README.md) or open an issue. You can also contact [wrebisz@redhat.com](mailto:wrebisz@redhat.com) or [tguzik@redhat.com](mailto:tguzik@redhat.com).
