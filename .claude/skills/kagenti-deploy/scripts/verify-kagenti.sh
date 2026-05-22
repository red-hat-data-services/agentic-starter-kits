#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-agents}"

echo "========================================="
echo "Kagenti Integration Verification"
echo "Namespace: $NAMESPACE"
echo "========================================="
echo ""

# Check namespace label
echo "1. Checking namespace label..."
NAMESPACE_LABEL=$(oc get namespace "$NAMESPACE" -o jsonpath='{.metadata.labels.kagenti-enabled}' 2>/dev/null || echo "")
if [ "$NAMESPACE_LABEL" = "true" ]; then
    echo "   [PASS] Namespace labeled for discovery"
else
    echo "   [FAIL] Namespace NOT labeled (should be: kagenti-enabled=true)"
fi

echo ""

# Get all deployments with kagenti labels
# Note: kagenti.io/type=agent is added by the controller when AgentRuntime is created
echo "2. Checking deployment labels..."
DEPLOYMENTS=$(oc get deployments -n "$NAMESPACE" -l kagenti.io/type=agent -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")

if [ -n "$DEPLOYMENTS" ]; then
    for deployment in $DEPLOYMENTS; do
        PROTOCOL_LABEL=$(oc get deployment "$deployment" -n "$NAMESPACE" -o jsonpath='{.metadata.labels.protocol\.kagenti\.io/a2a}' 2>/dev/null || echo "")
        if [ "$PROTOCOL_LABEL" = "true" ]; then
            echo "   [PASS] $deployment has required labels"
        else
            echo "   [WARN] $deployment has kagenti.io/type but missing protocol label"
        fi
    done
else
    echo "   [FAIL] No deployments with kagenti.io/type=agent found"
    echo "   (This label is added by the controller when AgentRuntime is created)"
fi

echo ""

# Check AgentRuntimes
echo "3. Checking AgentRuntimes..."
oc get agentruntime -n "$NAMESPACE" 2>/dev/null || echo "   No AgentRuntimes found"

echo ""

# Check AgentCards (created automatically by AgentRuntime)
echo "4. Checking AgentCards..."
AGENTCARDS=$(oc get agentcard -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")
if [ -n "$AGENTCARDS" ]; then
    oc get agentcard -n "$NAMESPACE"
else
    echo "   No AgentCards found (may still be creating)"
fi

echo ""

# Check sync status for each AgentCard
echo "5. Checking sync status..."
if [ -n "$AGENTCARDS" ]; then
    for agentcard in $AGENTCARDS; do
        SYNCED=$(oc get agentcard "$agentcard" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Synced")].status}' 2>/dev/null || echo "Unknown")
        AGENT_NAME=$(oc get agentcard "$agentcard" -n "$NAMESPACE" -o jsonpath='{.status.card.name}' 2>/dev/null || echo "Unknown")

        if [ "$SYNCED" = "True" ]; then
            echo "   [PASS] $AGENT_NAME: SYNCED"
        else
            echo "   [FAIL] $agentcard: NOT SYNCED (status: $SYNCED)"
        fi
    done
else
    echo "   No AgentCards to check"
fi

echo ""
echo "========================================="
echo "Summary"
echo "========================================="
echo ""

# Get kagenti UI URL
KAGENTI_HOST=$(oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}' 2>/dev/null || echo "Not found")
echo "Kagenti UI:"
echo "   https://$KAGENTI_HOST"
echo ""

# Final health check
if [ "$NAMESPACE_LABEL" = "true" ] && [ -n "$AGENTCARDS" ]; then
    ALL_SYNCED=true
    for agentcard in $AGENTCARDS; do
        SYNCED=$(oc get agentcard "$agentcard" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Synced")].status}' 2>/dev/null || echo "False")
        if [ "$SYNCED" != "True" ]; then
            ALL_SYNCED=false
        fi
    done

    if [ "$ALL_SYNCED" = "true" ]; then
        echo "[PASS] ALL CHECKS PASSED - Agents are visible in Kagenti!"
    else
        echo "[FAIL] SYNC ISSUE - Check the steps above"
        echo ""
        echo "Troubleshooting:"
        echo "  1. Check kagenti controller logs:"
        echo "     oc logs -n kagenti-system deployment/kagenti-controller-manager --tail=50"
    fi
else
    echo "[FAIL] SETUP INCOMPLETE - Check namespace labels and AgentRuntime CRs"
fi

echo ""
