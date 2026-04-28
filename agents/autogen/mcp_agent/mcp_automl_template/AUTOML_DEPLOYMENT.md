# AutoML Experiment, Deployment, and MCP Server

This guide walks through: **(1)** creating an AutoML experiment on Red Hat OpenShift AI, **(2)** deploying the best model, and **(3)** using that deployment with this MCP server so tools (e.g. `invoke_churn`) call your live model.

It is based on the [Red Hat AI examples – Predict Customer Churn tutorial](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/main/examples/automl/churn_prediction_tutorial.md). You can follow the same pattern for other datasets (e.g. credit risk) by swapping the pipeline inputs and schema.

---

## Overview

| Phase | What you do |
|-------|-------------|
| **1. AutoML experiment** | Create a project, S3 connections, run the AutoML pipeline (e.g. Telco Churn), view the leaderboard. |
| **2. Deploy best model** | Register the chosen model, set up the AutoGluon ServingRuntime (KServe), deploy the model, get the inference URL and token. |
| **3. Use with MCP server** | Set `DEPLOYMENT_URL` and `DEPLOYMENT_TOKEN` in `.env`; run the MCP server; tools will POST to your deployment. |

---

## Prerequisites

- Access to **Red Hat OpenShift AI** (self-managed or cloud).
- Permissions to create projects, connections, pipelines, workbenches, and deployments.
- This repo with the MCP AutoML server (see main [README](README.md) for Python/setup).

---

## Phase 1: Create and run the AutoML experiment

Follow the [churn prediction tutorial](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/main/examples/automl/churn_prediction_tutorial.md) up to and including **View the leaderboard**. Summary:

### 1.1 Create a project

- In OpenShift AI, go to **Projects** and create a new project (e.g. `customer-churn-ml` or `credit-risk-ml`).

### 1.2 Create S3 connections

Create two S3-compatible connections in the project:

1. **Results storage** – for pipeline artifacts and leaderboard (e.g. `automl-results-s3`). You will use this when configuring the Pipeline Server.
2. **Training data** – for the dataset (e.g. `customer-churn-data-s3`). Note the **connection name**; you will use it as `train_data_secret_name` in the pipeline run.

See: [Create the S3 connections](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-create-the-s3-connections).

### 1.3 Configure the Pipeline Server

- In your project, open **Pipelines** (or project details) and **Configure pipeline server**.
- Set the **Object storage connection** to the same bucket/credentials as your **results** S3 connection so runs and artifacts (leaderboard, models) are stored there.
- Choose **Default database** or **External MySQL** as needed. Create/Save and wait until the Pipeline Server is ready.

See: [Configure the Pipeline Server](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-configure-the-pipeline-server).

### 1.4 Create a workbench with connections

- In **Workbenches**, create a workbench and **attach** both the results and training-data S3 connections so you can access artifacts and data without a restart.

See: [Create workbench with connections attached](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-create-workbench-with-connections-attached).

### 1.5 Upload the dataset to S3

- Download the dataset (e.g. [WA_FnUseC_TelcoCustomerChurn.csv](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/data/WA_FnUseC_TelcoCustomerChurn.csv) for churn).
- Upload it to the bucket used by the **training data** connection. Note the **bucket name** and **object key** (path) for the pipeline run.

See: [Upload the training dataset to S3](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-upload-the-training-dataset-to-s3).

### 1.6 Add the AutoML pipeline and run it

- Get the compiled AutoML pipeline from the repo: [autogluon_tabular_training_pipeline](https://github.com/LukaszCmielowski/pipelines-components/tree/rhoai_automl/pipelines/training/automl/autogluon_tabular_training_pipeline) (branch `rhoai_automl`), e.g. [pipeline.yaml](https://github.com/LukaszCmielowski/pipelines-components/tree/rhoai_automl/pipelines/training/automl/autogluon_tabular_training_pipeline/pipeline.yaml).
- In OpenShift AI **Pipelines**, add it as a new **Pipeline Definition** (upload/create from YAML).
- Create a **pipeline run** with at least:
  - **train_data_secret_name** – name of the training-data S3 connection
  - **train_data_bucket_name** – bucket name
  - **train_data_file_key** – object key of the CSV (e.g. `data/WA_FnUseC_TelcoCustomerChurn.csv`)
  - **label_column** – e.g. `Churn`
  - **task_type** – e.g. `binary`
  - **top_n** – e.g. `3`
- Start the run and wait for completion.

See: [Add the AutoML pipeline](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-add-the-automl-pipeline-as-a-pipeline-definition), [Run AutoML with the required inputs](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-run-automl-with-the-required-inputs).

### 1.7 View the leaderboard

- Open the run **Artifacts** and locate the **leaderboard** (e.g. HTML). Download or open it and pick the **best model** (e.g. top-ranked) to deploy.

See: [View the leaderboard](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-view-the-leaderboard).

---

## Phase 2: Deploy the best model

Follow the tutorial from **Model Registry** through **Deployment Scoring**.

### 2.1 Register the model (optional but recommended)

- Create a **Model registry** (one-time, if not already done) under **Settings** → **Model resources and operations** → **AI registry settings**.
- In **Registry** → **Model registry**, **Register model**:
  - **Model location**: Object storage (S3), using the same artifact store as your pipeline.
  - **Path**: root folder of one refitted predictor (e.g. under `.../autogluon-models-full-refit/<task_id>/model_artifact/<ModelName>_FULL/`).
  - Set **Model name**, **Version**, and **Source model format** (e.g. custom / AutoGluon), then **Register**.

See: [Model Registry](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-model-registry).

### 2.2 Prepare the AutoGluon ServingRuntime (KServe)

- **Build the serving image** on the cluster (ImageStream + BuildConfig) using the [tutorial’s YAML](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-prepare-the-servingruntime-for-autogluon-with-kserve) (Git source, Dockerfile, output to ImageStream).
- **Create the ServingRuntime** from the tutorial’s ServingRuntime YAML:
  - Set `metadata.namespace` to your project.
  - Set `spec.containers[0].image` to the built image (e.g. `image-registry.openshift-image-registry.svc:5000/<namespace>/autogluonkserveimagev1:latest`).
- In OpenShift AI: **Settings** → **Serving runtimes** → **Add serving runtime** → upload the YAML, select **REST** and **Predictive model**, then **Create**.

See: [Prepare the ServingRuntime for AutoGluon with KServe](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-prepare-the-servingruntime-for-autogluon-with-kserve).

### 2.3 Deploy the model

- **Projects** → *your project* → **Deployments** → **Deploy model**.
- **Model location**: S3; use the path to the refitted model (same as registry or from run artifacts).
- **Model type**: Predictive model.
- **Model framework**: e.g. **autogluon - 1**.
- **Serving runtime**: **AutoGluon ServingRuntime for KServe**.
- In **Advanced settings**:
  - **Require token authentication** – enable if you want to use a Bearer token (recommended for the MCP server).
  - **Make model deployment available through an external route** – enable so you can call the endpoint from your machine (for the MCP server).
- **Deploy model** and wait until the deployment is running.

See: [Model Deployment](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-model-deployment).

### 2.4 Get the inference URL and token

- Open the **deployment details**. Under **Inference endpoint**, copy the **external** URL (only if you enabled the external route).
- **Deployment URL** for the MCP server is the **predict** endpoint, for example:
  - `<EXTERNAL_BASE_URL>/v1/models/<MODEL_NAME>:predict`
  where `<MODEL_NAME>` is the deployment’s **Resource name** (lowercase, no spaces). Example: `https://my-model-myproject.apps.example.com/v1/models/my-churn-model:predict`
- **Token** (if you enabled token auth): **Projects** → *your project* → **Deployments** → expand the deployment → use the **Token secret** value as `DEPLOYMENT_TOKEN`.

See: [Deployment Scoring](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-deployment-scoring) for the exact request format (e.g. `instances` with per-field arrays). The MCP server sends payloads in that same shape.

---

## Phase 3: Use the deployment with the MCP server

### 3.1 Match the tool schema to the deployment

The MCP server sends a JSON body like:

```json
{
  "instances": [
    { "feature1": [value1], "feature2": [value2], ... }
  ]
}
```

Your deployment (e.g. AutoGluon churn) expects one object per instance with the **same feature names** as in training. This repo provides `churn_schema.json` and the tool `invoke_churn` in `tools_config.yaml`. The schema properties match the churn model’s inputs (e.g. `gender`, `tenure`, `Contract`, `Churn`, etc. as in the [tutorial’s curl example](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md#-deployment-scoring)).

Set `DEPLOYMENT_URL` (and `DEPLOYMENT_TOKEN` if used) to your churn predict endpoint. To add another tool, add a new JSON Schema and entry in `tools_config.yaml` with its own `schema_path` and the same `deployment_url_env` / `deployment_token_env` if needed.

### 3.2 Set environment variables

In the MCP server directory, ensure `.env` exists and contains the deployment values from Phase 2:

```bash
mv template.env .env
```

Edit `.env`:

- **DEPLOYMENT_URL** = full predict URL, e.g. `https://my-model-myproject.apps.example.com/v1/models/my-churn-model:predict`
- **DEPLOYMENT_TOKEN** = token from the deployment’s Token secret (leave empty or omit if you did not enable token auth)

Keep `LLAMA_STACK_CLIENT_*` (or other LLM vars) if you use the demo client; see main [README](README.md).

### 3.3 Run the MCP server and call the tool

1. Start the server:

   ```bash
   python mcp_automl/mcp_server.py
   ```

2. Use the deployment via MCP:
   - **Demo client:** run `python mcp_automl/interact_with_mcp.py` and ask a question that triggers the tool (e.g. churn).
   - **Cursor:** add the MCP server with URL `http://127.0.0.1:8000/sse` (see [README – Attaching to Cursor and Ollama](README.md#attaching-to-cursor-and-ollama)).
   - **Ollama:** use an MCP-capable client with the same URL, or use the demo client with Ollama as the LLM.

The tool will POST to `DEPLOYMENT_URL` with `Authorization: Bearer <DEPLOYMENT_TOKEN>` and the validated input as `instances`; the response (e.g. `predictions`) is returned to the caller.

---

## Quick reference

| Step | Where | What to set / do |
|------|--------|-------------------|
| AutoML run | OpenShift AI Pipelines | Pipeline definition, run params (train_data_*, label_column, task_type, top_n) |
| Leaderboard | Run Artifacts | Pick best model for deployment |
| Deploy model | Project → Deployments | S3 path, AutoGluon runtime, external route, token auth |
| Inference URL | Deployment details | `<base>/v1/models/<resource-name>:predict` |
| Token | Deployment → Token secret | `DEPLOYMENT_TOKEN` in `.env` |
| MCP server | `.env` | `DEPLOYMENT_URL`, `DEPLOYMENT_TOKEN` |
| Tool schema | `tools_config.yaml` + `churn_schema.json` | Match deployment input features |

---

## References

- [Red Hat AI examples – Predict Customer Churn (AutoML)](https://github.com/red-hat-data-services/red-hat-ai-examples/blob/automl_sample/examples/automl/churn_prediction_tutorial.md) – full tutorial (project, S3, pipeline, leaderboard, predictor notebook, model registry, ServingRuntime, deployment, scoring).
- [autogluon_tabular_training_pipeline](https://github.com/LukaszCmielowski/pipelines-components/tree/rhoai_automl/pipelines/training/automl/autogluon_tabular_training_pipeline) – pipeline source (branch `rhoai_automl`).
- [KServe V1 Protocol](https://kserve.github.io/website/docs/concepts/architecture/data-plane/v1-protocol) – inference request/response format.
- This repo’s [README](README.md) – MCP server setup, tools, Cursor/Ollama, and `.env`.
