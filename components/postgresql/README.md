# `components/postgresql` — PostgreSQL for Agent Memory

A lightweight Helm chart that deploys a single-replica PostgreSQL instance on OpenShift/Kubernetes.
Designed for agents that need persistent database storage (e.g., `react_with_database_memory`,
`ci_failure_summarizer`).

## What This Chart Deploys

- **Deployment** — single PostgreSQL 16 pod (Red Hat UBI image)
- **Service** — ClusterIP on port 5432 for in-cluster access
- **Secret** — database credentials (user, password, database name)
- **PersistentVolumeClaim** — data persistence across pod restarts (1 Gi default)

> **Scope:** This chart is intended for development and testing workloads. It runs a single
> replica with no replication, failover, connection pooling, or performance tuning. For
> production use, consider [Bitnami PostgreSQL](https://github.com/bitnami/charts/tree/main/bitnami/postgresql),
> [CloudNativePG](https://cloudnative-pg.io/), or a managed PostgreSQL service.

## Quick Start

```bash
# From the repository root
helm install postgresql components/postgresql/ \
  --set auth.password=changeme
```

This creates a PostgreSQL instance accessible at `postgresql:5432` within the cluster.

## Connecting an Agent

After deploying PostgreSQL, configure the agent's `.env` to point to the in-cluster service:

```ini
POSTGRES_HOST=postgresql
POSTGRES_PORT=5432
POSTGRES_DB=agent_memory
POSTGRES_USER=agent
POSTGRES_PASSWORD=changeme
```

Then deploy the agent with `make deploy`. The agent connects via the Kubernetes service DNS name.

> **Note:** The chart's `auth.*` values map to the agent's `POSTGRES_*` env vars as follows:
>
> | Chart value       | Agent env var       |
> |-------------------|---------------------|
> | `auth.username`   | `POSTGRES_USER`     |
> | `auth.password`   | `POSTGRES_PASSWORD` |
> | `auth.database`   | `POSTGRES_DB`       |
> | Service name      | `POSTGRES_HOST`     |
> | `service.port`    | `POSTGRES_PORT`     |

## Using an Existing PostgreSQL Instance

If PostgreSQL is already running in your cluster (or externally), skip this chart entirely.
Set the agent's `POSTGRES_*` env vars to point to your existing instance:

```ini
POSTGRES_HOST=my-existing-postgres.other-namespace.svc.cluster.local
POSTGRES_PORT=5432
POSTGRES_DB=agent_memory
POSTGRES_USER=myuser
POSTGRES_PASSWORD=mypassword
```

For cross-namespace access, use the fully qualified service DNS:
`<service-name>.<namespace>.svc.cluster.local`.

## Configuration

| Value                    | Description                          | Default                                     |
|--------------------------|--------------------------------------|---------------------------------------------|
| `image.repository`       | PostgreSQL container image           | `registry.redhat.io/rhel9/postgresql-16`    |
| `image.tag`              | Image tag                            | `1-1786484397`                              |
| `auth.username`          | Database user                        | `agent`                                     |
| `auth.password`          | Database password (**required**)     | `""`                                        |
| `auth.database`          | Database name                        | `agent_memory`                              |
| `persistence.enabled`    | Enable persistent storage            | `true`                                      |
| `persistence.size`       | PVC size                             | `1Gi`                                       |
| `persistence.storageClass` | StorageClass (empty = cluster default) | `""`                                     |
| `service.port`           | Service port                         | `5432`                                      |
| `resources.requests.memory` | Memory request                    | `256Mi`                                     |
| `resources.requests.cpu` | CPU request                          | `100m`                                      |
| `resources.limits.memory` | Memory limit                        | `512Mi`                                     |
| `resources.limits.cpu`   | CPU limit                            | `500m`                                      |

## Preview Manifests

```bash
helm template postgresql components/postgresql/ \
  --set auth.password=changeme
```

## Cleanup

```bash
helm uninstall postgresql
# PVC is retained by default — delete manually if no longer needed:
oc delete pvc postgresql-data
```
