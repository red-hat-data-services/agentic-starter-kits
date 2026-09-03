#!/usr/bin/env bash
set -euo pipefail

OC_VERSION="${1:-stable}"
OC_MIRROR_URL="https://mirror.openshift.com/pub/openshift-v4/clients/ocp/${OC_VERSION}/openshift-client-linux.tar.gz"
INSTALL_DIR="${RUNNER_TEMP:-/tmp}/oc-bin"
MAX_ATTEMPTS=3
RETRY_DELAY=10

mkdir -p "$INSTALL_DIR"

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  echo "::group::oc install attempt ${attempt}/${MAX_ATTEMPTS}"
  if curl -sSfL --retry 3 --retry-delay 5 --retry-all-errors \
       "$OC_MIRROR_URL" -o /tmp/oc.tar.gz \
     && tar xzf /tmp/oc.tar.gz -C "$INSTALL_DIR" oc \
     && "$INSTALL_DIR/oc" version --client; then
    rm -f /tmp/oc.tar.gz
    echo "::endgroup::"
    echo "✅ oc installed successfully on attempt ${attempt}"
    echo "$INSTALL_DIR" >>"$GITHUB_PATH"
    exit 0
  fi
  rm -f /tmp/oc.tar.gz
  echo "::endgroup::"
  echo "⚠️ oc install attempt ${attempt} failed"
  if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
    echo "Retrying in ${RETRY_DELAY}s..."
    sleep "$RETRY_DELAY"
  fi
done

echo "::error::Failed to install oc after ${MAX_ATTEMPTS} attempts"
exit 1
