# Jira Issue Templates

This folder holds **Markdown issue templates** for planning and tracking work in Jira. Each file under `templates/` is a reusable blueprint: YAML front matter sets default **project** (`RHAIENG`), **issue type**, **component** (Tooling Experience), **team**, and where applicable **activity type** custom fields; the body is placeholder sections you fill before creating or pasting into a ticket.

## `templates/`

| File | Issue type | Role |
|------|------------|------|
| `epic.md` | Epic | Large outcomes: business objective, technical approach, dependencies, epic-level acceptance criteria, and a shepherd checklist for breaking work into child issues. |
| `story.md` | Story | User-facing capability: value statement, approach, acceptance criteria (local + RHOAI + docs), testing strategy. Defaults to activity type **New Features**. |
| `task.md` | Task | Internal engineering work: goal, approach, regression risk, acceptance criteria, testing strategy. Defaults to activity type **Tech Debt & Quality**. |
| `bug.md` | Bug | Defects: description, repro steps, expected vs actual, workaround, impact, dependency chain, acceptance criteria, testing strategy. Same default activity type as tasks. |
| `spike.md` | Spike | Time-boxed research: objective, time-box, expected artifacts (design/POC/follow-on tickets). Defaults to activity type **Learning & Enablement**. |

## Usage

Copy the template that matches the work item, replace bracketed placeholders, and create the issue in Jira (or use your team’s import/automation if it consumes this front matter format). If you reuse this repo outside the original Jira project, edit the **YAML front matter** at the top of that template file and change `project`, `components`, Team Id (`customfield_10001`), and where present Activity Type (`customfield_10464`) to match your Jira instance.
