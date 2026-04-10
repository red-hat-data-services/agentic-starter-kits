---
# Jira Issue Template: Bug
type: Bug
project: RHAIENG
fields:
  issuetype:
    name: Bug
  components:
    - name: Tooling Experience
  # Team
  customfield_12313240:
    name: Tooling Experience
  # Activity Type
  customfield_12320841:
    name: Tech Debt & Quality
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

- [ ] Bug cannot be reproduced using the steps above
- [ ] Example runs successfully locally and on RHOAI
- [ ] CI/CD pipeline passes

## Testing Strategy

[Describe how the functionality will be tested and automated. Note areas requiring manual or complex testing that should be considered during story pointing and code review.]
