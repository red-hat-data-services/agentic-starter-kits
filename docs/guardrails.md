# Guardrails for Agents

This guide covers the guardrails options available on Red Hat OpenShift AI and how to add safety rails to your agents.

## Guardrailed Agent Example

A working example lives at [`agents/langgraph/examples/guardrailed_agent/`](../agents/langgraph/examples/guardrailed_agent/). It demonstrates:

- **Proxy pattern** — NeMo Guardrails sits between the agent and the LLM, requiring zero agent code changes
- **Content safety** — input + output classification against S1-S13 safety categories
- **Topic boundaries** — restricts the agent to banking-related questions only
- **Regex filtering** — instant pattern matching for jailbreak attempts
- **Two profiles** — `local` (self-check, single model) and `nemoguard` (dedicated NemoGuard/Nemotron classifiers per layer)

```text
User → Agent (port 8000) → NeMo Guardrails (port 8090) → LLM (port 11434)
```

See the [example README](../agents/langgraph/examples/guardrailed_agent/README.md) for setup, configuration, and testing instructions.

---

## NeMo Guardrails vs Guardrails Orchestrator

Two guardrails systems are available on Red Hat OpenShift AI. Both are managed by the TrustyAI Operator.

> **Note:** The FMS Guardrails Orchestrator is **legacy** and will be deprecated in a future version of RHOAI. Use NeMo Guardrails for new deployments. See the [RHOAI 3.4 guardrails docs](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/enabling_ai_safety_with_guardrails/enabling-ai-safety-with-guardrails_safety) for details.

### Recommendation

**Use NeMo Guardrails** for new agent deployments. It works as a transparent proxy — point your agent's `BASE_URL` at it and you're done, zero code changes. Supports content safety, topic boundaries, dialogue flow control, PII detection, and per-rail OpenTelemetry tracing.

The Guardrails Orchestrator remains available for existing deployments that rely on external Hugging Face detector models or standalone content checks, but new projects should use NeMo Guardrails.

### Comparison

Based on the [RHOAI official comparison](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/enabling_ai_safety_with_guardrails/enabling-ai-safety-with-guardrails_safety):

| Dimension | NeMo Guardrails | Guardrails Orchestrator (legacy) |
|-----------|----------------|------------------------|
| **Central component** | NeMo Guardrails server | Guardrails Orchestrator |
| **Deployment CRD** | `NemoGuardrails` CR (TrustyAI Operator) | `Guardrails` CR (TrustyAI Operator) |
| **Detection mechanism** | Built-in detection algorithms, custom Python functions (`@action` decorator) executing within the NeMo server pod, connectivity with external detection frameworks | Built-in detectors external to the Orchestrator (regex, Hugging Face models, Granite Guardian) |
| **Operational flow** | NeMo server coordinates internal logic and external calls; Colang for programmable detection flow | Orchestrator watches and calls detector services; detection flows fixed in ConfigMap |
| **Inference path** | User → NeMo Server → vLLM Model | User → Orchestrator → vLLM Model |
| **Language stack** | Python-based (FastAPI) | Rust-based (Tokio) |
| **Rail types** | Input, output, dialog, retrieval, execution — five rail types covering the full request lifecycle | Input and output detection only |
| **Conversation control** | Yes — Colang language for dialogue flows, topic boundaries, multi-turn policies | No — detection only, no conversation steering |
| **Standalone detection** | Yes — `/v1/guardrail/checks` endpoint | Yes — `/api/v2/text/detection/content` endpoint |
| **Observability** | OpenTelemetry per-rail spans via Tempo (gRPC) | OpenTelemetry metrics and tracing exporter |
| **Status on RHOAI** | Active development | Legacy — will be deprecated |
| **Origin** | NVIDIA (Apache 2.0) | IBM Research / Red Hat (Apache 2.0) |

### When to use each

**NeMo Guardrails** (recommended for all new deployments):

- You're building a conversational agent (chatbot, customer service, assistant)
- You need topic boundaries ("only answer banking questions")
- You need content safety classification (S1-S13 Llama Guard taxonomy)
- You want the proxy pattern — zero agent code changes
- You need dialogue flow control (authentication steps, standard operating procedures)
- You want to use NVIDIA's NemoGuard NIM models for classification
- You need per-rail OpenTelemetry tracing for observability

**Guardrails Orchestrator** (legacy — existing deployments only):

- You have existing deployments using Hugging Face detector models (Granite Guardian, DeBERTa prompt injection)
- You need standalone content checks independent of LLM inference
- You're running multiple LLM endpoints and want a shared detection layer

## References

- [NeMo Guardrails Documentation](https://docs.nvidia.com/nemo/guardrails/)
- [RHOAI Guardrails Overview (3.4)](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/enabling_ai_safety_with_guardrails/enabling-ai-safety-with-guardrails_safety) — comparison table, legacy notice
- [RHOAI NeMo Guardrails Docs (3.4)](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/enabling_ai_safety_with_guardrails/enabling-ai-safety-with-nemo-guardrails_nemo-guardrails) — deployment, OTel configuration
- [RHOAI Guardrails Orchestrator Docs (3.4, legacy)](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/enabling_ai_safety_with_guardrails/using-guardrails-for-ai-safety_safety) — detectors, orchestrator setup
- [Guardrailed Agent Example](../agents/langgraph/examples/guardrailed_agent/) — working example with setup, config, and tests
- [RHOAI NeMo Guardrails Demos](https://github.com/RedHatQuickCourses/rhoai_demos/tree/nemo-guardrails) — deployment patterns, PII detection, OTel + Tempo + Grafana, modular rail configs
