@AGENTS.md

# Claude-specific guidance

The `@AGENTS.md` include above provides structure, commands, code style, workflow,
pre-commit hooks, dependency management, commit conventions, and non-standard agent
details. The notes below cover things specific to Claude Code that AGENTS.md does
not address.

## Claude Code skills

This project has a companion skills plugin
([agentic-starter-kits-skills](https://github.com/red-hat-data-services/agentic-starter-kits-skills))
that automates common workflows. Key skills include:

- `integrate-tracing` -- end-to-end MLflow tracing integration for an agent
- `fit-check` -- validate whether a new agent belongs in the repo
- `add-behavioral-tests` / `run-behavioral-tests` -- scaffold and run behavioral tests
- `deploy-agents` -- deploy agents to OpenShift with auto-detected cluster config

Invoke skills with the `agentic-starter-kits-skills:` prefix (e.g.,
`/agentic-starter-kits-skills:integrate-tracing`). See CONTRIBUTING.md for the
full skill list and installation instructions.

## Workspace instructions for Claude Code deployments

When deploying Claude Code on OpenShift, `CLAUDE.md` can be mounted as a ConfigMap
to inject project-specific instructions into the session. Claude Code automatically
reads `CLAUDE.md` from the working directory. See
`agents/claude-code/README.md` for the mounting pattern.
