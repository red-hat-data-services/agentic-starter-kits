# `components/auth` — ServiceAccount Token Auth

This component provides a reusable ASGI middleware (`SATokenAuthMiddleware`) that enforces
Kubernetes ServiceAccount token-based authentication for agent routes.

It is designed for agentic-starter-kits agents that expose `/chat/completions` publicly and
need a lightweight machine-to-machine auth layer without managing static secrets.

## What This Middleware Enforces

For each protected HTTP request:

1. Extract `Authorization: Bearer <token>`
2. Validate token with Kubernetes `TokenReview`
3. Validate token audience (`AUTH_AUDIENCE`)
4. Validate caller identity against allowlist (`AUTH_ALLOWED_SERVICEACCOUNTS`)

Status behavior:

- `401` -> missing/malformed/invalid token or wrong audience
- `403` -> authenticated token from non-allowlisted caller
- `503` -> token validation infrastructure failure (e.g. `TokenReview` call failure)

`/health` remains excluded by default through `AUTH_EXCLUDE_PATHS`.

## How It Is Consumed by an Agent

For `react_agent`, consumption is:

1. Add optional auth dependency in `pyproject.toml` (`[project.optional-dependencies].auth`)
2. Conditionally import and register middleware in `main.py` when `AUTH_ENABLED=true`
3. Build image with `components/auth` copied into build context
4. Deploy with auth values (`auth.enabled`, `auth.audience`, `auth.allowedServiceAccounts`)

Environment variables used at runtime:

- `AUTH_ENABLED` (`true`/`false`)
- `AUTH_AUDIENCE` (required when `AUTH_ENABLED=true`, example: `langgraph-react-agent`)
- `AUTH_ALLOWED_SERVICEACCOUNTS` (comma-separated `namespace:name`)
- `AUTH_EXCLUDE_PATHS` (default `/health`)

## Manual Cluster Steps (End-to-End)

The steps below assume OpenShift and the `react_agent` deployment flow.

### 1) Prepare caller ServiceAccount

```bash
oc -n ci-testing create serviceaccount langgraph-react-agent-caller --dry-run=client -o yaml | oc apply -f -
```

### 2) Deploy agent with auth enabled

From `agents/langgraph/react_agent/.env`:

```dotenv
AUTH_ENABLED=true
AUTH_AUDIENCE=langgraph-react-agent
AUTH_ALLOWED_SERVICEACCOUNTS=ci-testing:langgraph-react-agent-caller
```

Then:

```bash
make build-openshift
make deploy
```

### 3) Generate caller token

```bash
TOKEN="$(oc create token langgraph-react-agent-caller -n ci-testing --audience=langgraph-react-agent --duration=15m)"
```

### 4) Call protected endpoint

```bash
ROUTE="$(oc -n ci-testing get route langgraph-react-agent -o jsonpath='{.spec.host}')"

curl -sS -X POST "https://${ROUTE}/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{"messages":[{"role":"user","content":"say hi"}]}'
```

Expected high-level outcomes:

- No token -> `401`
- Valid allowlisted caller token -> `200`
- Valid token from non-allowlisted caller -> `403`
- Wrong audience token -> `401`

## Why `test_deployment.py` Changed

`agents/langgraph/react_agent/tests/integration/test_deployment.py` is now intentionally
focused on deployment health only (`/health` smoke check).

Reason:

- Auth validation adds multiple identity/audience permutations and temporary caller SA setup.
- Keeping all of that in `test_deployment.py` made the test broad and harder to reason about.

Compensation (where coverage moved):

- `agents/langgraph/react_agent/tests/integration/test_auth.py` owns auth-specific setup and matrix:
  - `401` unauthenticated
  - `200` allowlisted caller
  - `403` non-allowlisted caller
  - `401` wrong audience

This split keeps deployment smoke validation simple while making auth behavior explicit and testable.
