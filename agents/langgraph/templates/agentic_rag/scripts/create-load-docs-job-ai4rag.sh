#!/bin/bash
# Helper script to create an OpenShift Job for loading documents with ai4rag

set -e

# Read env vars
source .env

NS=$(oc project -q)
JOB_NAME="load-docs-ai4rag-$(date +%s)"

echo "==> Creating Job: $JOB_NAME in namespace: $NS"

# Create Job YAML
cat > /tmp/${JOB_NAME}.yaml <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  namespace: ${NS}
spec:
  ttlSecondsAfterFinished: 600
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: load-docs
        image: ${CONTAINER_IMAGE}
        imagePullPolicy: Always
        command: ["/bin/bash", "-c"]
        args:
        - |
          set -e
          echo "==> Loading documents with ai4rag"
          # Read cert as PEM text (ai4rag requires content, not path)
          export MILVUS_SERVER_CERT=\$(cat /sandbox/data/certs/milvus-ca.crt)
          export PYTHONPATH=/sandbox/.local/lib/python3.12/site-packages:/sandbox/.local/lib64/python3.12/site-packages:/sandbox
          cd /sandbox/data
          /usr/bin/python3.12 load_documents_wrapper.py
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
        - name: DOCUMENTS_DIR
          value: "/sandbox/data"
        - name: CHUNK_SIZE
          value: "512"
EOF

# Apply Job
oc apply -f /tmp/${JOB_NAME}.yaml

echo "==> Waiting for job to complete (max 5min)..."
if ! oc wait --for=condition=complete --timeout=300s job/${JOB_NAME} -n ${NS}; then
  echo "ERROR: Job did not complete within 5 minutes"
  POD_NAME=$(oc get pods -l job-name=${JOB_NAME} -n ${NS} -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
  if [ -n "$POD_NAME" ]; then
    echo "==> Pod logs:"
    oc logs $POD_NAME -n ${NS}
  fi
  exit 1
fi

echo "==> Extracting collection name from job logs..."
POD_NAME=$(oc get pods -l job-name=${JOB_NAME} -n ${NS} -o jsonpath='{.items[0].metadata.name}')
COLLECTION=$(oc logs $POD_NAME -n ${NS} | grep -oE 'MILVUS_COLLECTION_NAME=[a-zA-Z0-9_]+' | tail -1 | cut -d= -f2)

if [ -z "$COLLECTION" ]; then
  echo "ERROR: failed to extract MILVUS_COLLECTION_NAME from logs"
  echo "==> Full job logs:"
  oc logs $POD_NAME -n ${NS}
  exit 1
fi

# Update .env
sed -i.bak "s|^MILVUS_COLLECTION_NAME=.*|MILVUS_COLLECTION_NAME=${COLLECTION}|" .env && rm -f .env.bak

# Cleanup
rm -f /tmp/${JOB_NAME}.yaml

echo ""
echo "✅ Documents loaded successfully!"
echo "   Collection: ${COLLECTION}"
echo "   Updated .env: MILVUS_COLLECTION_NAME=${COLLECTION}"
echo "   Job: ${JOB_NAME} (will auto-delete in 10 minutes)"
echo ""
echo "To view job logs:"
echo "  oc logs ${POD_NAME} -n ${NS}"
