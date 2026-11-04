# AutoML Experiment, Deployment, and MCP Server (RHOAI 3.6)

This guide walks through: **(1)** training a churn model with **AutoML** in Red Hat OpenShift AI 3.6, **(2)** deploying the best model with the built-in **AutoGluon ServingRuntime for KServe**, and **(3)** pointing this MCP server at the deployment so the `invoke_churn` tool returns live predictions.

It follows the [Red Hat AI examples – Predict Customer Churn tutorial](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/main/examples/automl/churn_prediction_tutorial.md) and uses its Telco churn dataset. The same pattern works for other tabular datasets: swap the CSV, label column, and JSON Schema.

> **What changed in 3.6:** AutoML is now a dashboard feature (**Develop & train → AutoML**, Technology Preview) and RHOAI ships an **AutoGluon ServingRuntime for KServe**. You no longer build a custom serving image, upload a ServingRuntime YAML, or import the pipeline definition by hand.

---

## Overview

| Phase | What you do |
|-------|-------------|
| **1. Prepare the project** | Project, S3 connections, pipeline server with the AutoML managed pipelines enabled. |
| **2. Run AutoML** | Start an optimization run from the AutoML UI and review the leaderboard. |
| **3. Register the model** | **⋮ → Register model** from the leaderboard (needs a Model Registry instance), or deploy straight from S3. |
| **4. Deploy the model** | Deploy with the built-in **AutoGluon ServingRuntime for KServe**. |
| **5. Point the MCP server at it** | Set `DEPLOYMENT_URL` (and optionally `DEPLOYMENT_TOKEN` / `DEPLOYMENT_CA_BUNDLE`), then run the MCP server and agent. |

---

## Prerequisites

- **Red Hat OpenShift AI 3.6** with the AutoML (Technology Preview) feature enabled in the dashboard.
- Permissions to create projects, connections, pipeline servers, and model deployments.
- **Cluster capacity:** AutoML training steps request up to **4 vCPU and 16 GiB memory** per pod (limits go much higher). At least one worker needs that much *unrequested* capacity, or the run sits in `Pending`. Two m5.2xlarge workers that also host RHOAI itself aren't enough; add a node first.
- An S3-compatible object store (AWS S3, ODF/NooBaa, Ceph RGW, or similar) with two buckets: one for pipeline results and one for training data.
- This repo with the MCP AutoML server (see the main [README](README.md) for setup).

---

## 1. Prepare the project

### 1.1 Create a project

In OpenShift AI, go to **Projects** and create a project (e.g. `customer-churn-ml`).

### 1.2 Create S3 connections

In the project, create two **S3 compatible object storage** connections:

1. **Results storage** (e.g. `automl-results-s3`) – the pipeline server stores run artifacts, the leaderboard, and trained models here.
2. **Training data** (e.g. `churn-data-s3`) – AutoML reads the CSV from here.

### 1.3 Configure the pipeline server with the AutoML pipelines

1. Open the project's **Pipelines** tab and choose **Configure pipeline server**.
2. Select the **results** connection for object storage, and choose the default or an external database.
3. Enable the AutoML managed pipelines (the form sets `managedPipelines.enabled: true` on the pipeline server). The AutoML UI refuses to start runs without them ("required managed pipelines not found in namespace").

Creating the pipeline server from YAML only needs the same flag:

```yaml
spec:
  apiServer:
    managedPipelines:
      enabled: true
```

> On 3.6 GA the operator defaults the managed-pipelines image. On early-access (EA) builds it pointed at an upstream image instead — there, set `managedPipelines.image` to the DSPO's `RELATED_IMAGE_ODH_PIPELINES_COMPONENTS_IMAGE` and list the pipelines explicitly (`autogluon-tabular-training-pipeline`, `autogluon-timeseries-training-pipeline`).

> The pipeline server can report `ManagedPipelineValid=False` ("Managed pipelines not configured or no explicit pipeline list") even when the pipelines are loaded and the AutoML UI works. If the AutoML page lists runs without an error, the pipelines are available.

---

## 2. Run AutoML

1. Go to **Develop & train → AutoML** and select your project.
2. Create an optimization run:
   - **Training data:** select the training-data connection and **Upload file** with [WA_FnUseC_TelcoCustomerChurn.csv](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/main/examples/automl/data/churn/input_data/WA_FnUseC_TelcoCustomerChurn.csv), or pick the object if it is already in the bucket.
   - **Task type:** **Binary classification**.
   - **Label column:** `Churn`.
   - **Top N** models to refit: e.g. `3`.
3. Start the run and wait for it to succeed. Training takes several minutes.
4. Open the run's **leaderboard** to compare the models.

---

## 3. Register the model

From the leaderboard, open the **⋮** menu on the model you want and choose **Register model**.

**Register model** requires a **Model Registry instance**. In 3.6 the model registry component can be `Managed` while no registry exists yet, and then registering doesn't work. A cluster admin can create one under **Settings → Model registries** (see [Managing model registries](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/latest/html/managing_model_registries/index)). For a scratch environment, this CR is enough:

```yaml
apiVersion: modelregistry.opendatahub.io/v1beta1
kind: ModelRegistry
metadata:
  name: churn-registry
  namespace: rhoai-model-registries
spec:
  rest: {}
  kubeRBACProxy: {}
  postgres:
    generateDeployment: true   # operator provisions a PostgreSQL instance; use an external DB in production
```

**Alternative without a registry:** skip registration and deploy straight from the **results** S3 connection, using the model artifact path that the AutoML run wrote to the results bucket.

The leaderboard's **⋮ → Save notebook** generates a notebook that loads the predictor, which is handy for checking predictions offline.

---

## 4. Deploy the model

Deploy from the registered model version (**Deploy**) or from **Projects → *your project* → Deployments → Deploy model**:

- **Model location:** the registered version, or the results S3 connection plus the model artifact path.
- **Serving runtime:** **AutoGluon ServingRuntime for KServe** (built in; no custom runtime needed).
- **Model framework:** `autogluon - 1`.
- **Deployment resource name:** e.g. `churn-model`. It appears in the inference URL.
- **Require token authentication:** recommended. Enabling it creates a service account token secret for the deployment.
- **Make deployed models available through an external route:** enable it only if you will call the model from outside the cluster (e.g. running the MCP server locally).

Wait until the deployment shows **Started**/**Ready**.

---

## 5. Point the MCP server at the model

The MCP server POSTs the validated tool input to `DEPLOYMENT_URL` in the KServe v1 format:

```json
{
  "instances": [
    { "tenure": [12], "Contract": ["Month-to-month"], "MonthlyCharges": [70.5], "gender": [null], "...": [null] }
  ]
}
```

Every property in `churn_schema.json` is sent, and that matters: **the AutoGluon server requires all 19 training columns** and rejects partial rows with a "required columns are missing" error. Optional properties the caller omits go as `null`, which the server accepts as missing values. The response's `predictions` array contains the predicted label only (e.g. `{"predictions":["Yes"]}`); the tool returns the first entry, or the whole response body if there is no `predictions`. (The serving runtime also accepts a `PREDICT_PROBA=true` model environment variable that returns per-class probabilities instead of labels — e.g. `{"predictions":[{"No":0.36,"Yes":0.64}]}` — but the tool's label parsing expects the default.)

### 5.1 Choose the URL

The deployment's **Inference endpoints** (deployment details) list an internal URL and, if you enabled it, an external one. Append the v1 predict path to whichever you use:

```text
<endpoint>/v1/models/<deployment-resource-name>:predict
```

- **MCP server in the same cluster** (`make deploy-mcp`): use the **internal** endpoint. With token authentication on, it is `https://<name>-predictor.<project>.svc.cluster.local:8443` (plain `http://…:8080` when auth is off). Get it from the deployment's **Inference endpoints** or with `oc get isvc <name> -o jsonpath='{.status.address.url}'`.
- **MCP server on your laptop** (`make run-mcp`): use the **external** route URL.

### 5.2 Token (only if token authentication is on)

`DEPLOYMENT_TOKEN` is optional. Leave it empty for deployments without token authentication, and the server then sends no `Authorization` header.

To get the token:

- **Dashboard:** **Projects → *your project* → Deployments**, expand the deployment, and copy the token under **Token authentication**.
- **CLI:** the token lives in a service-account token secret named after the deployment:

  ```bash
  oc get secrets -n <project> | grep <deployment-resource-name>
  oc get secret <token-secret-name> -n <project> -o jsonpath='{.data.token}' | base64 -d
  ```

In-cluster callers need one extra thing: the auth proxy in front of the model checks that the token's service account can `get` the InferenceService in the project. Bind a Role granting it (`apiGroups: ["serving.kserve.io"], resources: ["inferenceservices"], verbs: ["get"]`, optionally restricted to the deployment's resource name) to the service account the MCP server runs as, and create a token secret for that service account.

### 5.3 TLS for in-cluster HTTPS endpoints

Internal KServe endpoints are typically served with certificates signed by the OpenShift **service CA**, which isn't in the default trust store. When `DEPLOYMENT_URL` is an internal `https://` URL, point `DEPLOYMENT_CA_BUNDLE` at the service CA. It's mounted in every pod:

```bash
DEPLOYMENT_CA_BUNDLE=/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt
```

`make deploy-mcp` passes it from `.env` to the MCP server deployment. External routes use the cluster's ingress certificate and normally need no CA setting.

### 5.4 Set the variables and run

In the parent `mcp_agent/` directory's `.env`:

```bash
DEPLOYMENT_URL=https://churn-model-customer-churn-ml.apps.example.com/v1/models/churn-model:predict
DEPLOYMENT_TOKEN=<token, or leave empty>
# DEPLOYMENT_CA_BUNDLE=/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt   # in-cluster https only
```

Then, from `mcp_agent/`:

- **Local:** `make run-mcp`, then `make run-app` (AutoGen agent) or `make interact-mcp` (LangGraph demo client). Ask something like *"Will a customer with 2 months tenure, a month-to-month contract and $95 monthly charges churn?"*
- **OpenShift:** `make deploy-mcp` (reads `DEPLOYMENT_URL`, `DEPLOYMENT_TOKEN`, and `DEPLOYMENT_CA_BUNDLE` from `.env`), then deploy the agent with `make deploy`.

To add another model, add a JSON Schema and a `tools_config.yaml` entry with its own `schema_path` and `deployment_url_env`/`deployment_token_env`.

---

## Quick reference

| Step | Where | What to set / do |
|------|-------|------------------|
| Pipeline server | Project → Pipelines | Results S3 connection; AutoML managed pipelines enabled |
| AutoML run | Develop & train → AutoML | CSV, **Binary classification**, label `Churn`, top N |
| Register | Leaderboard → ⋮ → Register model | Requires a Model Registry instance |
| Deploy | Model registry / Project → Deployments | **AutoGluon ServingRuntime for KServe**, framework `autogluon - 1` |
| URL | Deployment details → Inference endpoints | `<endpoint>/v1/models/<resource-name>:predict` |
| Token | Deployment → Token authentication | `DEPLOYMENT_TOKEN` (optional) |
| CA | In-cluster https only | `DEPLOYMENT_CA_BUNDLE=/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt` |

---

## Appendix: running the AutoML pipeline directly

You can still run the AutoML pipeline from **Pipelines** instead of the AutoML UI, e.g. for automation. With the managed pipelines enabled (1.3), `autogluon-tabular-training-pipeline` is already in the project. Otherwise import it from [pipelines-components](https://github.com/opendatahub-io/pipelines-components/tree/main/pipelines/training/automl/autogluon_tabular_training_pipeline). Create a run with:

- `train_data_secret_name` – training-data connection name
- `train_data_bucket_name` – bucket
- `train_data_file_key` – object key of the CSV (e.g. `data/WA_FnUseC_TelcoCustomerChurn.csv`)
- `label_column` – `Churn`
- `task_type` – `binary`
- `top_n` – e.g. `3`

---

## Looking ahead (RHOAI 3.7)

[RHAISTRAT-1967](https://redhat.atlassian.net/browse/RHAISTRAT-1967) plans an `automl` plugin for rhoai-mcp that exposes AutoGluon deployments natively as MCP tools (list, get, and predict). This template shows the same pattern today with a schema-driven tool you control.

---

## References

- [Red Hat AI examples – Predict Customer Churn (AutoML)](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/main/examples/automl/churn_prediction_tutorial.md)
- [autogluon_tabular_training_pipeline](https://github.com/opendatahub-io/pipelines-components/tree/main/pipelines/training/automl/autogluon_tabular_training_pipeline) – pipeline source
- [KServe V1 Protocol](https://kserve.github.io/website/docs/concepts/architecture/data-plane/v1-protocol) – inference request/response format
- This repo's [README](README.md) – MCP server setup, tools, Cursor/Ollama, and `.env`
