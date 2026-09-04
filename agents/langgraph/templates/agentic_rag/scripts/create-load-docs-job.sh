#!/bin/bash
# Helper script to create a Kubernetes Job YAML for loading documents to Milvus

set -e

JOB_NAME="${1}"
CONTAINER_IMAGE="${2}"
MAAS_API_KEY="${3}"
MAAS_BASE_URL="${4}"
EMBEDDING_MODEL="${5}"
EMBEDDING_DIMENSION="${6}"
MILVUS_URI="${7}"
MILVUS_TOKEN="${8}"
MILVUS_SERVER_NAME="${9}"

cat <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  labels:
    app: langgraph-agentic-rag-load-docs
spec:
  ttlSecondsAfterFinished: 300
  template:
    metadata:
      labels:
        app: langgraph-agentic-rag-load-docs
    spec:
      restartPolicy: Never
      volumes:
      - name: script
        configMap:
          name: load-docs-script
      containers:
      - name: load-docs
        image: "${CONTAINER_IMAGE}"
        command: ["/bin/bash", "-c"]
        volumeMounts:
        - name: script
          mountPath: /scripts
        args:
        - |
          set -e
          echo "Installing dependencies..."
          python3 -m pip install -q pymilvus openai langchain-community
          echo "Loading documents..."
          python3 /scripts/load.py
          echo "Done!"
        env:
        - name: MAAS_API_KEY
          value: "${MAAS_API_KEY}"
        - name: MAAS_BASE_URL
          value: "${MAAS_BASE_URL}"
        - name: EMBEDDING_MODEL
          value: "${EMBEDDING_MODEL}"
        - name: EMBEDDING_DIMENSION
          value: "${EMBEDDING_DIMENSION}"
        - name: MILVUS_URI
          value: "${MILVUS_URI}"
        - name: MILVUS_TOKEN
          value: "${MILVUS_TOKEN}"
        - name: MILVUS_SERVER_CERT
          value: "/sandbox/data/certs/milvus-ca.crt"
        - name: MILVUS_SERVER_NAME
          value: "${MILVUS_SERVER_NAME}"
        - name: DOCUMENTS_DIR
          value: "/sandbox/data"
EOF
