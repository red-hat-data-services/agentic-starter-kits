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

Two guardrails systems are available on Red Hat OpenShift AI. They are complementary, not competing — use one or both depending on your needs.

### Recommendation

**Start with NeMo Guardrails** if you're building a conversational agent and need content safety, topic boundaries, or dialogue flow control. It works as a transparent proxy — point your agent's `BASE_URL` at it and you're done, zero code changes.

**Add the Guardrails Orchestrator** when you need infrastructure-level detection across multiple AI endpoints — toxicity classification via dedicated detector models, or standalone content checks independent of inference.

### Comparison

| Dimension | NeMo Guardrails | Guardrails Orchestrator |
|-----------|----------------|------------------------|
| **What it does** | Transparent proxy between agent and LLM. Checks every request/response against configured rails (content safety, topic boundaries, regex, dialogue flows) | Request orchestrator that coordinates calls to external detector services (regex, HF models, Granite Guardian) |
| **Integration model** | Proxy pattern — agent's `BASE_URL` points at NeMo instead of the LLM. Zero agent code changes | Orchestrator pattern — sits between client and model server, routes to detector services via REST/gRPC |
| **Configuration** | YAML (`config.yaml`) + Colang scripts (`.co`) + classification prompts (`prompts.yml`) | ConfigMap with detector/generator specs. Detectors deployed as separate services |
| **Rail types** | Input, output, dialog, retrieval, execution — five rail types covering the full request lifecycle | Input and output detection. No dialogue flow management |
| **Conversation control** | Yes — Colang language for defining dialogue flows, topic boundaries, multi-turn policies | No — detection only, no conversation steering |
| **Detection approach** | In-process: LLM-based classification (self-check or dedicated models like NemoGuard-8B), regex, YARA injection, Presidio PII detection | External detector servers: HF models (e.g., `granite-guardian-hap-38m`), vLLM models (e.g., `granite-guardian-3.1-2b`), built-in regex |
| **Standalone detection** | Yes — `/v1/guardrail/checks` endpoint (used by Gen AI Studio for per-request inline moderation) | Yes — `/api/v2/text/detection/content` endpoint for detection without inference |
| **Deployment on RHOAI** | `NemoGuardrails` CRD (TrustyAI Operator) — Technology Preview | `GuardrailsOrchestrator` CRD (TrustyAI Operator) — GA since RHOAI 2.19 |
| **Origin** | NVIDIA (Apache 2.0) | IBM Research / Red Hat (Apache 2.0) |

### When to use each

**NeMo Guardrails:**

- You're building a conversational agent (chatbot, customer service, assistant)
- You need topic boundaries ("only answer banking questions")
- You need content safety classification (S1-S13 Llama Guard taxonomy)
- You want the proxy pattern — zero agent code changes
- You need dialogue flow control (authentication steps, standard operating procedures)
- You want to use NVIDIA's NemoGuard NIM models for classification

**Guardrails Orchestrator:**

- You want to use Hugging Face detector models (Granite Guardian, DeBERTa prompt injection)
- You need standalone content checks independent of LLM inference
- You're running multiple LLM endpoints and want a shared detection layer
- You need a GA-supported solution on RHOAI today (NeMo Guardrails is Technology Preview)

**Using both together:**

NeMo Guardrails handles conversational safety (topic boundaries, content classification, PII detection, dialogue flows) at the agent level. The Guardrails Orchestrator handles infrastructure-level detection (toxicity via dedicated detector models, custom classifiers) across your model serving fleet. They operate at different layers and complement each other.

## Observability

NeMo Guardrails supports native [OpenTelemetry tracing](https://docs.nvidia.com/nemo/microservices/latest/guardrails/observability.html) with per-rail spans — showing which rail fired, the classification result, and latency for each layer. This lets you assess guardrail performance and debug false positives/negatives.

```yaml
# Add to config.yaml to enable per-rail tracing
tracing:
  enabled: true
  span_format: opentelemetry
  adapters:
    - name: OpenTelemetry
```

Traces can be viewed in Jaeger, Tempo, or any OTel-compatible backend. For a complete OTel + Tempo + Grafana setup on OpenShift, see the [rhoai_demos with_otel example](https://github.com/RedHatQuickCourses/rhoai_demos/tree/nemo-guardrails/nemo_openshift/with_otel).

See the [guardrailed agent README](../agents/langgraph/examples/guardrailed_agent/README.md#tracing-and-observability) for setup instructions.

## Future capabilities

- **Action rails** ([RHAIRFE-1629](https://redhat.atlassian.net/browse/RHAIRFE-1629)) — NeMo Guardrails will add validation of agent tool-call arguments against business policies (e.g., "transfer amount must be under $10,000")
- **Trajectory rails** ([RHAIRFE-1382](https://redhat.atlassian.net/browse/RHAIRFE-1382)) — detection of suspicious agent behavior patterns across multi-step tool use sequences

## References

- [NeMo Guardrails Documentation](https://docs.nvidia.com/nemo/guardrails/)
- [RHOAI NeMo Guardrails Docs](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/enabling_ai_safety_with_guardrails/enabling-ai-safety-with-nemo-guardrails_nemo-guardrails)
- [RHOAI Guardrails Orchestrator Docs](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.5/html/enabling_ai_safety_with_guardrails/using-guardrails-for-ai-safety_safety)
- [TrustyAI Guardrails Orchestrator — Red Hat Research](https://research.redhat.com/blog/article/guardrailing-large-language-models-with-trustyai-guardrails-orchestrator/)
- [Guardrailed Agent Example](../agents/langgraph/examples/guardrailed_agent/) — working example with setup, config, and tests
- [RHOAI NeMo Guardrails Demos](https://github.com/RedHatQuickCourses/rhoai_demos/tree/nemo-guardrails) — deployment patterns, PII detection, OTel + Tempo + Grafana, modular rail configs
