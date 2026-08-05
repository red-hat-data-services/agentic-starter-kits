#!/usr/bin/env python3
"""Launch NeMo Guardrails server with OTel TracerProvider configured.

NeMo's OpenTelemetry adapter requires an SDK TracerProvider to be set
before it initializes — otherwise spans go to NoOp. On RHOAI the
container handles this; locally this script bridges the gap.

All CLI args are forwarded to ``nemoguardrails server``.
"""

import os
import sys


def _configure_otel() -> bool:
    if os.environ.get("GUARDRAILS_TRACING_ENABLED", "").lower() != "true":
        return False

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False

    protocol = os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    if protocol == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

    service_name = os.environ.get("OTEL_SERVICE_NAME", "nemo-guardrails")
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    print(f"OpenTelemetry enabled: endpoint={endpoint} service={service_name}")
    return True


_configure_otel()

sys.argv = ["nemoguardrails", "server", *sys.argv[1:]]
from nemoguardrails.cli import app  # noqa: E402

app()
