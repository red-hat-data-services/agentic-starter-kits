# Using Agentic Starter Kits with OGX Showroom

Connect agentic-starter-kits agents to an OGX server deployed on OpenShift via [ogx-showroom](https://github.com/opendatahub-io/ogx-showroom).

## Prerequisites

- OGX deployed on your cluster (see the ogx-showroom [helm-getting-started](https://github.com/opendatahub-io/ogx-showroom/blob/main/docs/helm-getting-started.md) guide)
- `oc` CLI logged in to the cluster
- `jq` installed
- [uv](https://docs.astral.sh/uv/) installed
- This repo cloned locally

## 1. Get OGX Credentials

The showroom deploys Keycloak for auth. Extract the endpoint and a bearer token:

```bash
NS=redhat-ods-applications  # adjust if your OGX was installed in a different namespace

OGX_URL=$(oc get route ogx-distribution -n $NS -o jsonpath='{.spec.host}')
KEYCLOAK_HOST=$(oc get route keycloak -n $NS -o jsonpath='{.spec.host}')
CLIENT_SECRET=$(oc get secret keycloak-secret -n $NS -o jsonpath='{.data.KEYCLOAK_CLIENT_SECRET}' | base64 -d)
USER_PASSWORD=$(oc get secret keycloak-secret -n $NS -o jsonpath='{.data.KEYCLOAK_USER_PASSWORD}' | base64 -d)

TOKEN=$(curl -s "https://${KEYCLOAK_HOST}/realms/ogx-demo/protocol/openid-connect/token" \
  -d "grant_type=password&client_id=ogx&client_secret=${CLIENT_SECRET}&username=user&password=${USER_PASSWORD}" \
  | jq -r .access_token)
```

> **Note:** If your cluster uses self-signed certificates, you may need to add `-k` to the curl commands. Avoid `-k` in production -- configure curl to trust your cluster's CA instead.

Verify connectivity by listing available models:

```bash
curl -s "https://${OGX_URL}/v1/models" \
  -H "Authorization: Bearer $TOKEN" | jq '.data[].id'
```

You should see at least an inference model (e.g. `vllm-inference/llama-3-2-3b`) and an embedding model (e.g. `vllm-embedding/nomic-embed-text-v1.5`). Note these model IDs -- you'll need them below.

## 2. ReAct Agent (Smoke Test)

A simple ReAct agent with a dummy tool. Use this to confirm your OGX connection works before moving to the RAG demo.

### 2.1 Set Up

```bash
cd agents/langgraph/templates/react_agent
make init
make env
```

### 2.2 Configure

Edit `.env` with your OGX details:

```ini
API_KEY=<paste $TOKEN value here>
BASE_URL=https://<your OGX_URL>/v1
MODEL_ID=vllm-inference/llama-3-2-3b
```

> **Note:** Replace the model ID with whatever inference model your cluster serves. Run the `/v1/models` query from step 1 to check.

### 2.3 Run

```bash
make run-cli
```

This starts an interactive chat. Type a question and confirm you get a response from the model. Type `quit` to exit.

To run as a FastAPI server instead:

```bash
make run-app
```

This starts on `http://localhost:8000` with `POST /chat/completions` and `GET /health`.

## 3. Agentic RAG

This agent exercises three OGX services: vLLM inference (chat), vLLM embeddings (vector search), and Milvus (vector storage). It ingests sample documents, embeds them into a vector store, and retrieves relevant chunks to ground the LLM's answers.

### 3.1 Set Up

```bash
cd agents/langgraph/templates/agentic_rag
make init
make env
```

### 3.2 Configure

Edit `.env`:

```ini
API_KEY=<paste $TOKEN value here>
BASE_URL=https://<your OGX_URL>/v1
MODEL_ID=vllm-inference/llama-3-2-3b

EMBEDDING_MODEL=vllm-embedding/nomic-embed-text-v1.5
EMBEDDING_DIMENSION=768
VECTOR_STORE_PROVIDER=milvus-remote
VECTOR_STORE_ID=
DOCS_TO_LOAD=./data/sample_knowledge.txt
```

> **Note:** `VECTOR_STORE_PROVIDER` must be `milvus-remote` -- this is the provider ID registered in the OGX server for its remote Milvus instance (you can verify with `curl "https://${OGX_URL}/v1/providers" -H "Authorization: Bearer $TOKEN" | jq '.data[] | select(.api=="vector_io")'`). The default `milvus` in `.env.example` targets a local Milvus Lite database and won't work here. Match `EMBEDDING_DIMENSION` to your embedding model (768 for nomic-embed-text-v1.5).

### 3.3 Load Documents

Ingest the sample knowledge base into the vector store:

```bash
make load-docs
```

This chunks `data/sample_knowledge.txt`, generates embeddings via the OGX embedding endpoint, creates a vector store in Milvus, and writes the new `VECTOR_STORE_ID` back into `.env`.

Expected output:

```text
Vector store created: id=vs_abcd1234-...
Loading documents from directory...
Created 14 chunks (filtered out empty/separator chunks)
Done! 14 chunks inserted into vector store vs_abcd1234-...
```

### 3.4 Run

```bash
make run-cli
```

Try questions that match the sample knowledge base (LangChain, LangGraph, RAG, vector databases, agent architectures). The agent will retrieve relevant chunks and produce a grounded answer.

Example interaction:

```text
You: What is RAG and how does it work?
Assistant: Based on provided documents, RAG stands for Retrieval-Augmented Generation.
It is a technique that combines information retrieval with text generation...
```

Questions outside the knowledge base (e.g. "What is the weather?") will return "I couldn't find relevant information in the provided documents."

## Token Refresh

The Keycloak JWT token expires after approximately 1 hour. To refresh it, re-run the token command from step 1 and update the `API_KEY` value in your `.env` file.
