---
# Jira Issue Template: Epic
type: Epic
project: RHAIENG
fields:
  issuetype:
    name: Epic
  components:
    - name: Tooling Experience
  # Team
  customfield_12313240:
    name: Tooling Experience
  # Epic Name (required for Epics)
  customfield_12311141: ""
---

## Business Objective

[State the overarching goal, customer need, or framework capability being delivered. e.g., Deliver an E2E agentic example using CrewAI with tool-calling on RHOAI.]

## Technical Approach

[High-level architecture or technical plan drafted by the Feature Shepherd. Include target framework, deployment pattern (local + RHOAI), and any POC links.]

## External Dependencies

[List any cross-team dependencies, upstream framework blockers, or RHOAI platform requirements. If none, state "None".]

## Epic Acceptance Criteria

- [ ] E2E example is functional locally and deployed on RHOAI
- [ ] Documentation and README are complete and reviewed
- [ ] CI/CD pipeline passes for the example

## Shepherd Breakdown Checklist

- [ ] Epic is broken down into properly sized Stories, Tasks, and Spikes.
- [ ] Child tickets meet the Definition of Ready (clear intent, AC defined, pointed).
- [ ] Work is delegated across the team to build shared expertise and prevent knowledge silos.
