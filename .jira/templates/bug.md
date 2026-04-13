---
# Jira Issue Template: Bug
type: Bug
project: RHAIENG
fields:
  issuetype:
    name: Bug
  components:
    - name: Tooling Experience
  # Team (Tooling Experience)
  customfield_10001: "ec74d716-af36-4b3c-950f-f79213d08f71-1611"
  # Activity Type
  customfield_10464:
    id: "12228"
    value: Tech Debt & Quality
---

## Description

[Brief summary of the broken functionality. e.g., LangGraph ReAct agent example fails on RHOAI due to deprecated API call.]

## Steps to Reproduce

1. [Step 1]
2. [Step 2]
3. [Step 3]

## Expected Outcome

[What should have happened?]

## Actual Outcome

[What actually happened? Include logs, error messages, or stack traces.]

## Workaround

[Is there a temporary way to bypass this issue? If none, state "None".]

## Impact

[Who is affected and how severely? e.g., All users following the CrewAI quickstart cannot complete the deployment step.]

## Dependency Chain

[Explicitly call out any upstream framework bugs or RHOAI platform issues blocking this fix. If none, state "None".]

## Acceptance Criteria

1. Bug cannot be reproduced using the steps above
2. Example runs successfully locally and on RHOAI
3. CI/CD pipeline passes

## Testing Strategy

[Describe how the functionality will be tested and automated. Note areas requiring manual or complex testing that should be considered during story pointing and code review.]
