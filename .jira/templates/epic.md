---
# Jira Issue Template: Epic
type: Epic
project: RHAIENG
fields:
  issuetype:
    name: Epic
  components:
    - name: Tooling Experience
  # Team (Tooling Experience)
  customfield_10001: "ec74d716-af36-4b3c-950f-f79213d08f71-1611"
---

## Business Objective

[State the overarching goal, customer need, or framework capability being delivered. e.g., Deliver an E2E agentic example using CrewAI with tool-calling on RHOAI.]

## Technical Approach

[High-level architecture or technical plan drafted by the Feature Shepherd. Include target framework, deployment pattern (local + RHOAI), and any POC links.]

## External Dependencies

[List any cross-team dependencies, upstream framework blockers, or RHOAI platform requirements. If none, state "None".]

## Epic Acceptance Criteria

1. E2E example is functional locally and deployed on RHOAI
2. Documentation and README are complete and reviewed
3. CI/CD pipeline passes for the example

## Shepherd Breakdown Checklist

1. Epic is broken down into properly sized Stories, Tasks, and Spikes.
2. Child tickets meet the Definition of Ready (clear intent, AC defined, pointed).
3. Work is delegated across the team to build shared expertise and prevent knowledge silos.
