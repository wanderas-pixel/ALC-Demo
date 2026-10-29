"""OpenTelemetry (OTel) Full Observability Instrumentation for ACME Co. ABO Agents.

Configures distributed tracing (Cloud Trace), custom agent & tool metrics (Cloud Monitoring),
and trace-correlated structured logging (Cloud Logging) for ADK 2.0 agents running on
Google Cloud Agent Platform Runtime (Vertex AI Agent Engine) behind Agent Gateway.

Emits OpenTelemetry GenAI (`gen_ai.*`) and Agent Platform (`agent.*`) semantic attributes:
- `gen_ai.system`: "gcp.vertex_agent_engine"
- `gen_ai.request.model`: "gemini-2.5-flash"
- `agent.runtime.environment`: "vertex-ai-agent-engine"
- `agent.runtime.resource_name`: projects/genai-demos-391416/locations/us-central1/reasoningEngines/...
- `agent.gateway.id`: "acme-abo-agent-gateway"
- `agent.identity.principal`: SPIFFE / IAM Agent Identity principal
- `agent.identity.service_account`: GCP IAM Service Account email
- `agent.registry.agent_id`: Canonical Agent Registry URI
"""

from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import functools
import json
import logging
import os
import time
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional

try:
    from opentelemetry import context as otel_context
    from opentelemetry import metrics, trace
    from opentelemetry.propagate import extract, inject
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.trace import SpanKind, Status, StatusCode

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

logger = logging.getLogger("acme_abo.otel")

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

# In-memory ring buffer of recent OTel spans so the Web Cockpit & Gateway can inspect live traces
RECENT_OTEL_SPANS: List[Dict[str, Any]] = []

AGENT_IDENTITY_MAP: Dict[str, str] = {
    "abo_supervisor_agent": (
        f"principal://agents.googleapis.com/projects/{PROJECT_ID}/"
        f"locations/{LOCATION}/agentIdentities/sa-agent-supervisor"
    ),
    "alarm_triage_agent": (
        f"principal://agents.googleapis.com/projects/{PROJECT_ID}/"
        f"locations/{LOCATION}/agentIdentities/sa-agent-triage"
    ),
    "cross_layer_rca_agent": (
        f"principal://agents.googleapis.com/projects/{PROJECT_ID}/"
        f"locations/{LOCATION}/agentIdentities/sa-agent-rca"
    ),
    "energy_optimization_agent": (
        f"principal://agents.googleapis.com/projects/{PROJECT_ID}/"
        f"locations/{LOCATION}/agentIdentities/sa-agent-energy"
    ),
    "energy_optimizer_agent": (
        f"principal://agents.googleapis.com/projects/{PROJECT_ID}/"
        f"locations/{LOCATION}/agentIdentities/sa-agent-energy"
    ),
    "remediation_dispatch_agent": (
        f"principal://agents.googleapis.com/projects/{PROJECT_ID}/"
        f"locations/{LOCATION}/agentIdentities/sa-agent-remediation"
    ),
    "predictive_drift_agent": (
        f"principal://agents.googleapis.com/projects/{PROJECT_ID}/"
        f"locations/{LOCATION}/agentIdentities/sa-agent-energy"
    ),
}

AGENT_SA_EMAIL_MAP: Dict[str, str] = {
    "abo_supervisor_agent": f"sa-agent-supervisor@{PROJECT_ID}.iam.gserviceaccount.com",
    "alarm_triage_agent": f"sa-agent-triage@{PROJECT_ID}.iam.gserviceaccount.com",
    "cross_layer_rca_agent": f"sa-agent-rca@{PROJECT_ID}.iam.gserviceaccount.com",
    "energy_optimization_agent": f"sa-agent-energy@{PROJECT_ID}.iam.gserviceaccount.com",
    "energy_optimizer_agent": f"sa-agent-energy@{PROJECT_ID}.iam.gserviceaccount.com",
    "remediation_dispatch_agent": f"sa-agent-remediation@{PROJECT_ID}.iam.gserviceaccount.com",
    "predictive_drift_agent": f"sa-agent-energy@{PROJECT_ID}.iam.gserviceaccount.com",
}

_INITIALIZED = False
_SPAN_COUNTER: Any = None
_LATENCY_HISTOGRAM: Any = None
_CLOUD_TRACE_ENABLED = False
_CLOUD_MONITORING_ENABLED = False


def init_agent_otel(service_name: str = "acme-abo-agent-platform-runtime") -> Dict[str, Any]:
    """Initializes OpenTelemetry TracerProvider (Cloud Trace) and MeterProvider (Cloud Monitoring)."""
    global _INITIALIZED, _SPAN_COUNTER, _LATENCY_HISTOGRAM, _CLOUD_TRACE_ENABLED, _CLOUD_MONITORING_ENABLED
    if _INITIALIZED:
        return get_otel_status()

    if not OTEL_AVAILABLE:
        logger.info("OpenTelemetry SDK not installed in current env; using lightweight span recorder.")
        _INITIALIZED = True
        return get_otel_status()

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "2.0.0",
            "cloud.provider": "gcp",
            "cloud.Account.id": PROJECT_ID,
            "cloud.region": LOCATION,
            "cloud.platform": "gcp_agent_platform_runtime",
            "agent.runtime.name": os.environ.get(
                "ACME_AGENT_RUNTIME", "acme-abo-agent-platform-runtime"
            ),
            "agent.runtime.resource_name": os.environ.get(
                "ACME_AGENT_ENGINE_RESOURCE_NAME",
                f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/acme-abo-multi-agent-system",
            ),
            "agent.gateway.name": os.environ.get("ACME_AGENT_GATEWAY", "acme-abo-agent-gateway"),
            "agent.registry.name": os.environ.get("ACME_AGENT_REGISTRY", "acme-abo-agent-registry"),
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    if os.environ.get("ENABLE_CONSOLE_OTEL", "false").lower() == "true":
        tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    # Export real spans to Google Cloud Trace by default unless explicitly disabled
    if os.environ.get("USE_GCP_OTEL_EXPORTER", "true").lower() != "false":
        try:
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

            cloud_trace_exporter = CloudTraceSpanExporter(project_id=PROJECT_ID)
            tracer_provider.add_span_processor(BatchSpanProcessor(cloud_trace_exporter))
            _CLOUD_TRACE_ENABLED = True
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not initialize CloudTraceSpanExporter: %s", exc)

    trace.set_tracer_provider(tracer_provider)

    # Export real custom agent metrics to Google Cloud Monitoring
    metric_readers = []
    if os.environ.get("USE_GCP_OTEL_EXPORTER", "true").lower() != "false":
        try:
            from opentelemetry.exporter.cloud_monitoring import CloudMonitoringMetricsExporter

            monitoring_exporter = CloudMonitoringMetricsExporter(project_id=PROJECT_ID)
            metric_readers.append(
                PeriodicExportingMetricReader(monitoring_exporter, export_interval_millis=30000)
            )
            _CLOUD_MONITORING_ENABLED = True
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not initialize CloudMonitoringMetricsExporter: %s", exc)

    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
    metrics.set_meter_provider(meter_provider)

    meter = metrics.get_meter("acme_abo.agent_platform", "2.0.0")
    _SPAN_COUNTER = meter.create_counter(
        name="acme_abo_agent_invocations_total",
        description="Total ADK 2.0 agent and tool invocations across Agent Gateway and Runtime",
        unit="1",
    )
    _LATENCY_HISTOGRAM = meter.create_histogram(
        name="acme_abo_agent_latency_ms",
        description="End-to-end latency of ADK 2.0 agent and tool spans in milliseconds",
        unit="ms",
    )

    _INITIALIZED = True
    return get_otel_status()


def get_otel_status() -> Dict[str, Any]:
    return {
        "otel_sdk_available": OTEL_AVAILABLE,
        "initialized": _INITIALIZED,
        "cloud_trace_exporter_active": _CLOUD_TRACE_ENABLED,
        "cloud_monitoring_exporter_active": _CLOUD_MONITORING_ENABLED,
        "project_id": PROJECT_ID,
        "w3c_traceparent_propagation": True,
    }


def extract_trace_context(headers: Optional[Dict[str, str]] = None) -> Any:
    """Extracts W3C traceparent / baggage context from incoming HTTP headers."""
    if not OTEL_AVAILABLE or not headers:
        return None
    carrier = {k.lower(): v for k, v in headers.items() if isinstance(v, str)}
    return extract(carrier)


def inject_trace_context(headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Injects current W3C traceparent context into outbound HTTP headers."""
    carrier: Dict[str, str] = dict(headers or {})
    if OTEL_AVAILABLE:
        inject(carrier)
    return carrier


def _emit_cloud_logging_correlated_entry(span_record: Dict[str, Any]) -> None:
    """Writes a structured JSON log line correlated with Google Cloud Trace (`logging.googleapis.com/trace`)."""
    trace_id = span_record["trace_id"]
    span_id = span_record["span_id"]
    log_payload = {
        "severity": "INFO" if span_record["status"] == "OK" else "ERROR",
        "message": f"[OTel Span] {span_record['span_name']} ({span_record['duration_ms']} ms) — {span_record['attributes'].get('agent.name')} -> {span_record['attributes'].get('agent.tool.name')}",
        "logging.googleapis.com/trace": f"projects/{PROJECT_ID}/traces/{trace_id}",
        "logging.googleapis.com/spanId": span_id,
        "logging.googleapis.com/trace_sampled": True,
        "otel_span": span_record,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    # Emit to stdout only when running in Cloud Run / Agent Runtime container
    if os.environ.get("K_SERVICE") or os.environ.get("EMIT_STRUCTURED_OTEL_LOGS", "false").lower() == "true":
        print(json.dumps(log_payload), flush=True)


def record_otel_span(
    span_name: str,
    agent_name: str,
    tool_name: str,
    attributes: Optional[Dict[str, Any]] = None,
    duration_ms: float = 0.0,
    status: str = "OK",
    parent_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Creates a real OpenTelemetry span (exported to Cloud Trace) and records its metadata."""
    init_agent_otel()
    principal = AGENT_IDENTITY_MAP.get(agent_name, AGENT_IDENTITY_MAP["abo_supervisor_agent"])
    sa_email = AGENT_SA_EMAIL_MAP.get(agent_name, AGENT_SA_EMAIL_MAP["abo_supervisor_agent"])
    runtime_res = os.environ.get(
        "ACME_AGENT_ENGINE_RESOURCE_NAME",
        f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/acme-abo-multi-agent-system",
    )
    model_name = os.environ.get("ACME_ADK_MODEL", "gemini-2.5-flash")

    merged_attrs: Dict[str, Any] = {
        "gen_ai.system": "gcp.vertex_agent_engine",
        "gen_ai.request.model": model_name,
        "agent.runtime.name": "acme-abo-agent-platform-runtime",
        "agent.runtime.resource_name": runtime_res,
        "agent.gateway.id": os.environ.get("ACME_AGENT_GATEWAY", "acme-abo-agent-gateway"),
        "agent.gateway.policy_verdict": "ALLOW",
        "agent.registry.id": f"registry://acme-abo-agent-registry/{agent_name}:2.0.0",
        "agent.identity.principal": principal,
        "agent.identity.service_account": sa_email,
        "agent.name": agent_name,
        "agent.tool.name": tool_name,
        "otel.duration_ms": round(duration_ms, 2),
    }
    if attributes:
        for k, v in attributes.items():
            if v is not None:
                merged_attrs[str(k)] = v if isinstance(v, (str, int, float, bool)) else str(v)

    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    traceparent = f"00-{trace_id}-{span_id}-01"

    if OTEL_AVAILABLE:
        tracer = trace.get_tracer("acme_abo.agent_platform", "2.0.0")
        ctx = extract_trace_context(parent_headers) if parent_headers else None
        with tracer.start_as_current_span(
            span_name,
            context=ctx,
            kind=SpanKind.INTERNAL,
            attributes=merged_attrs,
        ) as span:
            if status != "OK":
                span.set_status(Status(StatusCode.ERROR, status))
            else:
                span.set_status(Status(StatusCode.OK))
            span_ctx = span.get_span_context()
            if span_ctx and span_ctx.is_valid:
                trace_id = format(span_ctx.trace_id, "032x")
                span_id = format(span_ctx.span_id, "016x")
                traceparent = f"00-{trace_id}-{span_id}-01"

        if _SPAN_COUNTER is not None:
            _SPAN_COUNTER.add(
                1,
                {
                    "agent_name": agent_name,
                    "tool_name": tool_name,
                    "status": "OK" if status == "OK" else "ERROR",
                },
            )
        if _LATENCY_HISTOGRAM is not None:
            _LATENCY_HISTOGRAM.record(
                max(duration_ms, 0.1),
                {"agent_name": agent_name, "tool_name": tool_name},
            )

    span_record = {
        "trace_id": trace_id,
        "span_id": span_id,
        "traceparent": traceparent,
        "cloud_trace_uri": f"projects/{PROJECT_ID}/traces/{trace_id}",
        "span_name": span_name,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "attributes": merged_attrs,
    }
    RECENT_OTEL_SPANS.append(span_record)
    if len(RECENT_OTEL_SPANS) > 150:
        RECENT_OTEL_SPANS.pop(0)

    _emit_cloud_logging_correlated_entry(span_record)
    return span_record


@contextmanager
def start_agent_span(
    span_name: str,
    agent_name: str,
    tool_name: str,
    attributes: Optional[Dict[str, Any]] = None,
    parent_headers: Optional[Dict[str, str]] = None,
) -> Iterator[Dict[str, Any]]:
    """Context manager that runs code inside an active OTel span and records duration & trace context."""
    init_agent_otel()
    t0 = time.perf_counter()
    holder: Dict[str, Any] = {
        "trace_id": uuid.uuid4().hex,
        "span_id": uuid.uuid4().hex[:16],
        "traceparent": "",
        "attributes": dict(attributes or {}),
    }
    status = "OK"
    try:
        yield holder
    except Exception as exc:
        status = f"ERROR: {exc}"
        raise
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        rec = record_otel_span(
            span_name=span_name,
            agent_name=agent_name,
            tool_name=tool_name,
            attributes=holder.get("attributes"),
            duration_ms=elapsed_ms,
            status=status,
            parent_headers=parent_headers,
        )
        holder.update(rec)


def traced_tool_span(agent_name: str, tool_name: str) -> Callable:
    """Decorator that wraps an ADK 2.0 tool execution in a real OpenTelemetry span."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            status = "OK"
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as exc:
                status = f"ERROR: {exc}"
                raise
            finally:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                record_otel_span(
                    span_name=f"adk.tool.{tool_name}",
                    agent_name=agent_name,
                    tool_name=tool_name,
                    attributes={"tool.kwargs_keys": ",".join(kwargs.keys())},
                    duration_ms=elapsed_ms,
                    status=status,
                )

        return wrapper

    return decorator
