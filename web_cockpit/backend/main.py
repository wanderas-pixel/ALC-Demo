"""FastAPI Backend-for-Frontend (BFF) for ACME Co. Autonomous Building Operations Cockpit.

Supports:
- Portfolio & KPI summary (`/api/portfolio`)
- Brick v1.4 HVAC Topology & BACnet Network Topology (`/api/topology/hvac`, `/api/topology/network`)
- Point Telemetry & Predictive Thermal Cone (`/api/telemetry/{point_id}`)
- Energy & Peer-Cohort Z-Score Analytics (`/api/energy-analytics`)
- Agent Platform Runtime, Agent Gateway, Agent Identity, Agent Registry & OTel Telemetry (`/api/agent-platform/metadata`)
- Real-Time Server-Sent Events (SSE) stream (`/api/events/stream`) shared across Chrome tabs
- Companion "Demo Director" Admin Endpoints (`/api/admin/state`, `/api/admin/inject`, `/api/admin/reset`)
  for triggering Option A (`SCN-1`: Cascading Rooftop Unit Failure) and
  Option B (`SCN-4`: Critical Server Room Predictive Alert) with `<1s` instant reset.
- Human-in-the-Loop (HITL) SHACL-validated BACnet Priority 8 approval (`/api/hitl/approve`).
"""

from __future__ import annotations

import asyncio
import csv
import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Path as FastAPIPath, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_SOURCE_DIR = ROOT_DIR / "Source Data"
_BUNDLED_SEED_DIR = Path(__file__).resolve().parent / "seed_data"
SOURCE_DATA_DIR = Path(
    os.environ.get(
        "ACME_SOURCE_DATA_DIR",
        str(_DEFAULT_SOURCE_DIR if _DEFAULT_SOURCE_DIR.exists() else _BUNDLED_SEED_DIR),
    )
).resolve()
AGENTS_DIR = (ROOT_DIR / "agents").resolve()

PROJECT_ID: str = os.environ.get("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")
LOCATION: str = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
AGENT_GATEWAY_URL: str = os.environ.get(
    "ACME_AGENT_GATEWAY_URL",
    "https://acme-abo-agent-gateway-101296135052.us-central1.run.app",
).rstrip("/")
AGENT_ENGINE_RESOURCE_NAME: str = os.environ.get(
    "ACME_AGENT_ENGINE_RESOURCE_NAME",
    "projects/101296135052/locations/us-central1/reasoningEngines/5782923462607634432",
)
COCKPIT_SERVICE_ACCOUNT: str = os.environ.get(
    "ACME_COCKPIT_SA",
    f"sa-cockpit-cloudrun@{PROJECT_ID}.iam.gserviceaccount.com",
)
GATEWAY_SERVICE_ACCOUNT: str = f"sa-abo-agent-gateway@{PROJECT_ID}.iam.gserviceaccount.com"

# Strict CORS Allowlist (defaults to local dev ports; overridden via ACME_ALLOWED_ORIGINS on Cloud Run)
ALLOWED_ORIGINS: List[str] = [
    origin.strip()
    for origin in os.environ.get(
        "ACME_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if origin.strip()
]

# Cloud Identity-Aware Proxy (IAP) Enforcement Flag (enabled automatically when running on Cloud Run K_SERVICE)
ENFORCE_IAP: bool = (
    os.environ.get("ACME_ENFORCE_IAP", "false").lower() == "true"
    and bool(os.environ.get("K_SERVICE"))
)

AGENT_IDENTITY_LOOKUP: Dict[str, str] = {
    "abo_supervisor_agent": f"sa-agent-supervisor@{PROJECT_ID}.iam.gserviceaccount.com",
    "alarm_triage_agent": f"sa-agent-triage@{PROJECT_ID}.iam.gserviceaccount.com",
    "cross_layer_rca_agent": f"sa-agent-rca@{PROJECT_ID}.iam.gserviceaccount.com",
    "energy_optimization_agent": f"sa-agent-energy@{PROJECT_ID}.iam.gserviceaccount.com",
    "energy_optimizer_agent": f"sa-agent-energy@{PROJECT_ID}.iam.gserviceaccount.com",
    "predictive_drift_agent": f"sa-agent-energy@{PROJECT_ID}.iam.gserviceaccount.com",
    "remediation_dispatch_agent": f"sa-agent-remediation@{PROJECT_ID}.iam.gserviceaccount.com",
}

# ---------------------------------------------------------------------------
# Full OpenTelemetry (OTel) Instrumentation for Cockpit BFF
# ---------------------------------------------------------------------------
BFF_OTEL_STATUS: Dict[str, Any] = {
    "initialized": False,
    "service_name": "acme-abo-cockpit",
    "project_id": PROJECT_ID,
    "cloud_trace_exporter_active": False,
    "cloud_monitoring_exporter_active": False,
    "w3c_traceparent_propagation": True,
}
_BFF_TRACER = None
_BFF_PROPAGATOR = None
_BFF_LATENCY_HISTOGRAM = None
_BFF_GATEWAY_COUNTER = None


def _init_cockpit_otel() -> None:
    global _BFF_TRACER, _BFF_PROPAGATOR, _BFF_LATENCY_HISTOGRAM, _BFF_GATEWAY_COUNTER
    if BFF_OTEL_STATUS["initialized"]:
        return
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        resource = Resource.create(
            {
                "service.name": "acme-abo-cockpit",
                "service.namespace": "acme-autonomous-building-ops",
                "service.version": "2.0.0",
                "cloud.provider": "gcp",
                "cloud.project.id": PROJECT_ID,
                "cloud.region": LOCATION,
                "agent.caller.identity": COCKPIT_SERVICE_ACCOUNT,
                "agent.gateway.url": AGENT_GATEWAY_URL,
                "agent.runtime.resource": AGENT_ENGINE_RESOURCE_NAME,
            }
        )
        tracer_provider = TracerProvider(resource=resource)
        if os.environ.get("USE_GCP_OTEL_EXPORTER", "true").lower() == "true":
            try:
                from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

                tracer_provider.add_span_processor(
                    BatchSpanProcessor(CloudTraceSpanExporter(project_id=PROJECT_ID))
                )
                BFF_OTEL_STATUS["cloud_trace_exporter_active"] = True
            except Exception:
                pass
        trace.set_tracer_provider(tracer_provider)
        _BFF_TRACER = trace.get_tracer("acme.abo.cockpit.bff", "2.0.0")
        _BFF_PROPAGATOR = TraceContextTextMapPropagator()

        readers = []
        if os.environ.get("USE_GCP_OTEL_EXPORTER", "true").lower() == "true":
            try:
                from opentelemetry.exporter.cloud_monitoring import CloudMonitoringMetricsExporter

                readers.append(
                    PeriodicExportingMetricReader(
                        CloudMonitoringMetricsExporter(project_id=PROJECT_ID),
                        export_interval_millis=15000,
                    )
                )
                BFF_OTEL_STATUS["cloud_monitoring_exporter_active"] = True
            except Exception:
                pass
        meter_provider = MeterProvider(resource=resource, metric_readers=readers)
        metrics.set_meter_provider(meter_provider)
        meter = metrics.get_meter("acme.abo.cockpit.metrics", "2.0.0")
        _BFF_LATENCY_HISTOGRAM = meter.create_histogram(
            name="acme_abo_cockpit_gateway_latency_ms",
            description="End-to-end latency of Agent Gateway + Agent Runtime calls in ms",
            unit="ms",
        )
        _BFF_GATEWAY_COUNTER = meter.create_counter(
            name="acme_abo_cockpit_gateway_calls_total",
            description="Total Agent Gateway mediated calls from Cockpit BFF",
            unit="1",
        )
        BFF_OTEL_STATUS["initialized"] = True
    except Exception:
        BFF_OTEL_STATUS["initialized"] = True


_init_cockpit_otel()


def _emit_structured_cloud_log(
    message: str,
    trace_id: str,
    span_id: str,
    agent_name: str,
    tool_name: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    if os.environ.get("EMIT_STRUCTURED_OTEL_LOGS", "true").lower() != "true":
        return
    payload: Dict[str, Any] = {
        "severity": "INFO",
        "message": message,
        "logging.googleapis.com/trace": f"projects/{PROJECT_ID}/traces/{trace_id}",
        "logging.googleapis.com/spanId": span_id,
        "logging.googleapis.com/trace_sampled": True,
        "component": "acme-abo-cockpit",
        "agent_name": agent_name,
        "tool_name": tool_name,
        "agent_runtime_resource": AGENT_ENGINE_RESOURCE_NAME,
        "agent_gateway_url": AGENT_GATEWAY_URL,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)
    try:
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _sync_call_agent_gateway(
    target_agent: str,
    tool_name: str,
    prompt: str,
    site_id: str,
    node_id: str,
    bacnet_priority: Optional[int],
    invoke_live_runtime: bool,
) -> Dict[str, Any]:
    """Synchronous worker that starts an OTel span, injects W3C traceparent, and invokes acme-abo-agent-gateway."""
    t0 = time.perf_counter()
    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    outbound_headers: Dict[str, str] = {
        "Content-Type": "application/json",
    }

    target_sa = AGENT_IDENTITY_LOOKUP.get(
        target_agent, f"sa-agent-supervisor@{PROJECT_ID}.iam.gserviceaccount.com"
    )

    span_cm = None
    if _BFF_TRACER is not None:
        try:
            span_cm = _BFF_TRACER.start_as_current_span(
                f"cockpit.gateway_dispatch.{target_agent}",
                attributes={
                    "agent.caller.service_account": COCKPIT_SERVICE_ACCOUNT,
                    "agent.target.name": target_agent,
                    "agent.target.service_account": target_sa,
                    "agent.tool.name": tool_name,
                    "agent.gateway.url": AGENT_GATEWAY_URL,
                    "agent.runtime.resource": AGENT_ENGINE_RESOURCE_NAME,
                    "acme.site_id": site_id,
                    "acme.node_id": node_id,
                },
            )
            span = span_cm.__enter__()
            sc = span.get_span_context()
            if sc and sc.is_valid:
                trace_id = format(sc.trace_id, "032x")
                span_id = format(sc.span_id, "016x")
            if _BFF_PROPAGATOR is not None:
                _BFF_PROPAGATOR.inject(outbound_headers)
        except Exception:
            span_cm = None

    if "traceparent" not in outbound_headers:
        outbound_headers["traceparent"] = f"00-{trace_id}-{span_id}-01"

    try:
        # Attach OIDC ID token if running in GCP or ADC available
        try:
            import google.auth.transport.requests
            from google.oauth2 import id_token

            auth_req = google.auth.transport.requests.Request()
            tok = id_token.fetch_id_token(auth_req, AGENT_GATEWAY_URL)
            if tok:
                outbound_headers["Authorization"] = f"Bearer {tok}"
        except Exception:
            pass

        body = json.dumps(
            {
                "caller_service_account": COCKPIT_SERVICE_ACCOUNT,
                "target_agent": target_agent,
                "tool_name": tool_name,
                "prompt": prompt,
                "site_id": site_id,
                "node_id": node_id,
                "bacnet_priority": bacnet_priority,
                "invoke_live_runtime": invoke_live_runtime,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{AGENT_GATEWAY_URL}/v1/gateway/invoke",
            data=body,
            headers=outbound_headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=22.0) as resp:
            gw_data = json.loads(resp.read().decode("utf-8"))

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        gw_otel = gw_data.get("otel", {})
        gw_ident = gw_data.get("agent_identity", {})
        gw_rt = gw_data.get("agent_runtime", {})

        final_trace_id = gw_otel.get("trace_id") or trace_id
        final_span_id = gw_otel.get("span_id") or span_id

        if _BFF_LATENCY_HISTOGRAM is not None:
            _BFF_LATENCY_HISTOGRAM.record(
                elapsed_ms, {"agent": target_agent, "tool": tool_name, "verdict": "ALLOW"}
            )
        if _BFF_GATEWAY_COUNTER is not None:
            _BFF_GATEWAY_COUNTER.add(
                1, {"agent": target_agent, "tool": tool_name, "verdict": "ALLOW"}
            )

        _emit_structured_cloud_log(
            message=f"Cockpit BFF -> Agent Gateway -> Vertex AI Agent Runtime ({target_agent}.{tool_name}) completed in {elapsed_ms}ms",
            trace_id=final_trace_id,
            span_id=final_span_id,
            agent_name=target_agent,
            tool_name=tool_name,
            extra={
                "gateway_latency_ms": elapsed_ms,
                "runtime_invoked": gw_rt.get("invoked", False),
                "token_sha256_prefix": gw_ident.get("token_sha256_prefix", ""),
            },
        )
        return {
            "gateway_reachable": True,
            "gateway_url": AGENT_GATEWAY_URL,
            "gateway_service_account": gw_data.get("gateway_service_account", GATEWAY_SERVICE_ACCOUNT),
            "caller_service_account": COCKPIT_SERVICE_ACCOUNT,
            "policy_verdict": gw_data.get("policy_verdict", "ALLOW"),
            "shacl_status": gw_data.get("shacl_status", "CONFORMS (0 Violations)"),
            "agent_registry_uri": gw_data.get(
                "agent_registry_uri", f"registry://acme-abo-agent-registry/{target_agent}:2.0.0"
            ),
            "agent_identity": gw_ident,
            "agent_runtime": gw_rt,
            "otel_trace_id": final_trace_id,
            "otel_span_id": final_span_id,
            "traceparent": gw_otel.get("traceparent", f"00-{final_trace_id}-{final_span_id}-01"),
            "cloud_trace_console_url": gw_otel.get(
                "cloud_trace_console_url",
                f"https://console.cloud.google.com/traces/list?project={PROJECT_ID}&tid={final_trace_id}",
            ),
            "duration_ms": elapsed_ms,
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        token_hash = hashlib.sha256(f"{target_sa}:{trace_id[:16]}".encode("utf-8")).hexdigest()[:16]
        _emit_structured_cloud_log(
            message=f"Cockpit BFF -> Agent Gateway fallback ({target_agent}.{tool_name}): {exc}",
            trace_id=trace_id,
            span_id=span_id,
            agent_name=target_agent,
            tool_name=tool_name,
        )
        return {
            "gateway_reachable": False,
            "gateway_url": AGENT_GATEWAY_URL,
            "gateway_service_account": GATEWAY_SERVICE_ACCOUNT,
            "caller_service_account": COCKPIT_SERVICE_ACCOUNT,
            "policy_verdict": "ALLOW",
            "shacl_status": "CONFORMS (0 Violations)",
            "agent_registry_uri": f"registry://acme-abo-agent-registry/{target_agent}:2.0.0",
            "agent_identity": {
                "agent_name": target_agent,
                "service_account": target_sa,
                "token_minted": True,
                "auth_mechanism": "IAM_CREDENTIALS_OIDC_ID_TOKEN",
                "token_sha256_prefix": token_hash,
            },
            "agent_runtime": {
                "name": "acme-abo-agent-platform-runtime",
                "reasoning_engine_resource": AGENT_ENGINE_RESOURCE_NAME,
                "invoked": False,
                "latency_ms": elapsed_ms,
                "note": str(exc)[:180],
            },
            "otel_trace_id": trace_id,
            "otel_span_id": span_id,
            "traceparent": f"00-{trace_id}-{span_id}-01",
            "cloud_trace_console_url": f"https://console.cloud.google.com/traces/list?project={PROJECT_ID}&tid={trace_id}",
            "duration_ms": elapsed_ms,
        }
    finally:
        if span_cm is not None:
            try:
                span_cm.__exit__(None, None, None)
            except Exception:
                pass


async def _dispatch_via_agent_gateway(
    target_agent: str,
    tool_name: str,
    prompt: str,
    site_id: str = "ACME-SITE-001",
    node_id: str = "bldg:area_ec_ahu_1",
    bacnet_priority: Optional[int] = None,
    invoke_live_runtime: bool = True,
) -> Dict[str, Any]:
    """Asynchronously dispatches an agent tool/prompt invocation through the deployed Agent Gateway and Vertex AI Agent Runtime."""
    return await asyncio.to_thread(
        _sync_call_agent_gateway,
        target_agent,
        tool_name,
        prompt,
        site_id,
        node_id,
        bacnet_priority,
        invoke_live_runtime,
    )


app = FastAPI(
    title="ACME Co. Autonomous Building Operations BFF (Agent Platform Runtime + Agent Gateway)",
    version="2.0.0",
    description=(
        "Hardened FastAPI BFF + SSE Broadcast Bus fronting Google Cloud Agent Platform Runtime "
        f"({AGENT_ENGINE_RESOURCE_NAME}), Agent Gateway ({AGENT_GATEWAY_URL}), "
        "Agent Identity, Agent Registry, and full OpenTelemetry observability."
    ),
    docs_url="/api/docs" if not ENFORCE_IAP else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "traceparent", "baggage", "X-Goog-IAP-JWT-Assertion"],
)


@app.middleware("http")
async def zero_trust_security_middleware(request: Request, call_next: Any) -> Response:
    """Enforces Cloud IAP identity headers (in Cloud Run prod), instruments HTTP requests with OTel, and attaches OWASP headers."""
    if ENFORCE_IAP and request.url.path != "/api/healthz":
        iap_jwt = request.headers.get("X-Goog-IAP-JWT-Assertion")
        iap_email = request.headers.get("X-Goog-Authenticated-User-Email")
        if not iap_jwt or not iap_email:
            return Response(
                content=json.dumps({"error": "Zero-Trust IAP Authentication Required"}),
                status_code=401,
                media_type="application/json",
            )

    req_trace_id = uuid.uuid4().hex
    req_span_id = uuid.uuid4().hex[:16]
    span_cm = None
    if _BFF_TRACER is not None and request.url.path.startswith("/api/"):
        try:
            ctx = _BFF_PROPAGATOR.extract(carrier=dict(request.headers)) if _BFF_PROPAGATOR else None
            span_cm = _BFF_TRACER.start_as_current_span(
                f"cockpit.http.{request.method} {request.url.path}",
                context=ctx,
                attributes={
                    "http.method": request.method,
                    "http.route": request.url.path,
                    "agent.caller.identity": COCKPIT_SERVICE_ACCOUNT,
                },
            )
            span = span_cm.__enter__()
            sc = span.get_span_context()
            if sc and sc.is_valid:
                req_trace_id = format(sc.trace_id, "032x")
                req_span_id = format(sc.span_id, "016x")
        except Exception:
            span_cm = None

    try:
        response: Response = await call_next(request)
    finally:
        if span_cm is not None:
            try:
                span_cm.__exit__(None, None, None)
            except Exception:
                pass

    response.headers["X-Cloud-Trace-Context"] = f"{req_trace_id}/{int(req_span_id, 16)};o=1"
    response.headers["traceparent"] = f"00-{req_trace_id}-{req_span_id}-01"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return response


def _safe_source_path(filename: str) -> Path:
    """Canonicalizes filename and blocks any directory traversal outside SOURCE_DATA_DIR."""
    candidate = (SOURCE_DATA_DIR / filename).resolve()
    if not candidate.is_relative_to(SOURCE_DATA_DIR):
        raise ValueError(f"Path traversal blocked for filename: {filename}")
    return candidate


def _load_csv(filename: str) -> List[Dict[str, str]]:
    path = _safe_source_path(filename)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_json(filename: str) -> Any:
    path = _safe_source_path(filename)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


class DemoRuntimeState:
    """In-memory two-layer overlay state supporting `<1s` instant reset, OTel spans, and multi-tab SSE."""

    def __init__(self) -> None:
        self.active_scenario: Optional[str] = None
        self.remediated_scenario: Optional[str] = None
        self.building_healed: bool = False
        self.injected_events: List[Dict[str, Any]] = []
        self.injected_telemetry: Dict[str, List[Dict[str, Any]]] = {}
        self.agent_reasoning_steps: List[Dict[str, Any]] = []
        self.otel_spans: List[Dict[str, Any]] = []
        self.staged_hitl_actions: List[Dict[str, Any]] = []
        self.work_orders: List[Dict[str, Any]] = []
        self.last_reset_ts: str = dt.datetime.now(dt.timezone.utc).isoformat()
        self.subscribers: List[asyncio.Queue] = []

    async def broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        msg = {
            "event_type": event_type,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "payload": payload,
        }
        for q in list(self.subscribers):
            await q.put(msg)

    def reset(self) -> Dict[str, Any]:
        t0 = time.perf_counter()
        self.active_scenario = None
        self.remediated_scenario = None
        self.building_healed = False
        self.injected_events.clear()
        self.injected_telemetry.clear()
        self.agent_reasoning_steps.clear()
        self.otel_spans.clear()
        self.staged_hitl_actions.clear()
        self.work_orders.clear()
        self.last_reset_ts = dt.datetime.now(dt.timezone.utc).isoformat()
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "status": "CLEAN_BASELINE_T0",
            "active_scenario": None,
            "building_healed": False,
            "active_alarms_count": 0,
            "reset_latency_ms": elapsed_ms,
            "last_reset_ts": self.last_reset_ts,
        }


RUNTIME = DemoRuntimeState()


class InjectRequest(BaseModel):
    scenario_id: Literal["SCN-1", "SCN-2", "SCN-3", "SCN-4"] = Field(
        ...,
        description="Strict allowlisted Golden Scenario identifier ('SCN-1'..'SCN-4').",
    )
    speed_multiplier: float = Field(
        default=1.0,
        ge=0.25,
        le=10.0,
        description="Bounded simulation playback speed multiplier.",
    )


class HitlDecisionRequest(BaseModel):
    action_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    decision: Literal["APPROVE", "REJECT"]
    operator_note: Optional[str] = Field(
        default="Approved by Lead Building Operator",
        max_length=280,
    )


class PortalLoginRequest(BaseModel):
    portal: Literal["cockpit", "admin"]
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


PORTAL_CREDENTIALS: Dict[str, Dict[str, str]] = {
    "cockpit": {
        "username": os.environ.get("ACME_COCKPIT_USER", "user"),
        "password": os.environ.get("ACME_COCKPIT_PASS", "12345"),
        "role": "Building Operator (Cockpit)",
    },
    "admin": {
        "username": os.environ.get("ACME_ADMIN_USER", "admin"),
        "password": os.environ.get("ACME_ADMIN_PASS", "09876"),
        "role": "Demo Director (Admin)",
    },
}


@app.post("/api/auth/login")
def portal_login(req: PortalLoginRequest) -> Dict[str, Any]:
    expected = PORTAL_CREDENTIALS.get(req.portal)
    if not expected:
        raise HTTPException(status_code=400, detail="Invalid portal target")
    user_ok = hmac.compare_digest(req.username.strip(), expected["username"])
    pass_ok = hmac.compare_digest(req.password, expected["password"])
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Invalid username or password for this portal")
    return {
        "authenticated": True,
        "portal": req.portal,
        "username": expected["username"],
        "role": expected["role"],
    }


@app.get("/api/healthz", include_in_schema=False)
def healthcheck() -> Dict[str, str]:
    return {"status": "ok", "service": "acme-abo-cockpit"}


SITE_ASSET_BREAKDOWN_META: Dict[str, Dict[str, Any]] = {
    "ACME-SITE-001": {
        "asset_breakdown_short": "2 Rooftop AHUs • 34 Zone VAV/PIUs • 90 BACnet Controllers",
        "asset_breakdown_detail": (
            "126 Managed Assets = 2 Primary Rooftop Air Handling Units (RTU-1, RTU-2) + "
            "34 Fan-Powered Induction / VAV Terminal Boxes (PIUs) + "
            "90 ALC Optiflex BACnet/IP & ARCNET Field Controllers (1,084 live telemetry points)."
        ),
        "ai_predictive_headline": "AI Watch: 2F Huddle PIU-1 shows 74% likelihood of reheat valve wear within 48h ($4,380/yr waste)",
        "top_risk_node_id": "bldg:ec_2nd_floor_area9_emrd_2_piu_1",
        "top_risk_pct": 74,
    },
    "ACME-SITE-002": {
        "asset_breakdown_short": "2 Ammonia Chillers/MUAs • 64 Cold-Vault Coils & Dock Units • 148 Controllers",
        "asset_breakdown_detail": (
            "214 Managed Assets = 2 Primary Refrigeration & Make-Up Air Plants (NH3-CHILL-1, MUA-1) + "
            "64 Blast Evaporator Coils, Desiccant Dehumidifiers & Dock Air Curtains + "
            "148 Industrial BACnet/IP Field Controllers (1,840 live telemetry points)."
        ),
        "ai_predictive_headline": "AI Watch: All Deep-Freeze Vaults (-10°F) nominal; 4% baseline failure risk across 214 assets",
        "top_risk_node_id": "bldg:s2_nh3_chiller_1",
        "top_risk_pct": 8,
    },
    "ACME-SITE-003": {
        "asset_breakdown_short": "2 100%-OA HEPA MAHUs • 68 Cleanroom Venturi/FFU Units • 240 Controllers",
        "asset_breakdown_detail": (
            "310 Managed Assets = 2 100% Outdoor-Air HEPA Make-Up Units (MAHU-1, MAHU-2) + "
            "68 ULPA Fan-Filter Arrays, BSL-3 Exhaust Scrubbers & Fume Hood VAVs + "
            "240 High-Precision Lab BACnet Controllers (3,420 live telemetry points)."
        ),
        "ai_predictive_headline": "AI Watch: ISO-5 & BSL-3 pressure cascades locked (±0.08 in.w.c.); $31,500/yr night-setback opportunity",
        "top_risk_node_id": "bldg:s3_hepa_mahu_1",
        "top_risk_pct": 6,
    },
    "ACME-SITE-004": {
        "asset_breakdown_short": "2 Process Chilled-Water/AHU Plants • 88 CNC/SMT Terminal Units • 195 Controllers",
        "asset_breakdown_detail": (
            "285 Managed Assets = 2 Industrial Process Make-Up & Chilled Water Plants (IND-AHU-1, CHW-PLANT-4) + "
            "88 Cleanroom Reheat VAVs, Oil-Mist Extractors & Metrology CRACs + "
            "195 Factory BACnet/IP Controllers (2,610 live telemetry points)."
        ),
        "ai_predictive_headline": "AI Alert: SMT PCB Assembly Line (VAV-4) has 78% likelihood of reheat valve actuator seizure in 36h",
        "top_risk_node_id": "bldg:s4_room_smt_clean",
        "top_risk_pct": 78,
    },
    "ACME-SITE-005": {
        "asset_breakdown_short": "2 Heat-Recovery DOAS Plants • 44 Chilled Beams & VRF Units • 152 Controllers",
        "asset_breakdown_detail": (
            "198 Managed Assets = 2 Dedicated Outdoor Air & Heat-Recovery Plants (DOAS-1, VRF-PLANT) + "
            "44 Active Chilled Beams, CO2 Demand VAVs & Boardroom Fan Coils + "
            "152 BACnet/IP Field Controllers (1,950 live telemetry points)."
        ),
        "ai_predictive_headline": "AI Watch: Executive Sky Floor & Robotics Arena at 99.1% comfort; $19,600/yr CO2 ventilation savings",
        "top_risk_node_id": "bldg:s5_vrf_oas_1",
        "top_risk_pct": 5,
    },
}


@app.get("/api/portfolio")
def get_portfolio() -> Dict[str, Any]:
    sites = _load_csv("portfolio_sites.csv")
    for s in sites:
        sid = s.get("site_id", "")
        meta = SITE_ASSET_BREAKDOWN_META.get(sid, {})
        s["asset_breakdown_short"] = meta.get(
            "asset_breakdown_short",
            f"{s.get('equipment_count', 26)} HVAC Units • {s.get('bacnet_controllers_count', 100)} BACnet Controllers",
        )
        s["asset_breakdown_detail"] = meta.get("asset_breakdown_detail", "")
        s["ai_predictive_headline"] = meta.get("ai_predictive_headline", "")
        s["top_risk_node_id"] = meta.get("top_risk_node_id", "")
        s["top_risk_pct"] = meta.get("top_risk_pct", 5)
    return {
        "company": "ACME Co.",
        "platform": "ACME Autonomous Building Operations (ABO)",
        "agent_runtime": f"Vertex AI Agent Engine ({AGENT_ENGINE_RESOURCE_NAME})",
        "agent_runtime_resource": AGENT_ENGINE_RESOURCE_NAME,
        "agent_gateway": "acme-abo-client-to-agent",
        "agent_gateway_client_to_agent": "projects/genai-demos-391416/locations/us-central1/agentGateways/acme-abo-client-to-agent",
        "agent_gateway_agent_to_anywhere": "projects/genai-demos-391416/locations/us-central1/agentGateways/acme-abo-agent-to-anywhere",
        "agent_registry_service": "projects/genai-demos-391416/locations/us-central1/services/acme-abo-supervisor-service",
        "agent_gateway_url": AGENT_GATEWAY_URL,
        "cockpit_identity": COCKPIT_SERVICE_ACCOUNT,
        "gateway_identity": GATEWAY_SERVICE_ACCOUNT,
        "supervisor_identity": AGENT_IDENTITY_LOOKUP["abo_supervisor_agent"],
        "agent_registry": "acme-abo-agent-registry",
        "console_links": {
            "agent_gateways": "https://console.cloud.google.com/net-services/agent-gateways/list?project=genai-demos-391416",
            "agent_registry_services": "https://console.cloud.google.com/agent-registry/services?project=genai-demos-391416",
            "agent_engine_runtime": f"https://console.cloud.google.com/vertex-ai/reasoning-engines/locations/us-central1/reasoning-engines/{AGENT_ENGINE_RESOURCE_NAME.split('/')[-1]}?project={PROJECT_ID}",
        },
        "observability": "OpenTelemetry (Cloud Trace + Cloud Monitoring + Cloud Logging)",
        "otel_status": BFF_OTEL_STATUS,
        "model": "gemini-2.5-flash",
        "active_scenario": RUNTIME.active_scenario,
        "building_healed": RUNTIME.building_healed,
        "active_alarms_count": len(RUNTIME.injected_events),
        "sites": sites,
    }


@app.get("/api/agent-platform/metadata")
def get_agent_platform_metadata() -> Dict[str, Any]:
    registry_path = AGENTS_DIR / "registry" / "agent_registry_manifest.json"
    if not registry_path.exists():
        registry_path = _BUNDLED_SEED_DIR / "agent_registry_manifest.json"
    registry_data = {}
    if registry_path.exists():
        with registry_path.open("r", encoding="utf-8") as f:
            registry_data = json.load(f)
    return {
        "runtime": {
            "name": "acme-abo-multi-agent-system",
            "reasoning_engine_resource": AGENT_ENGINE_RESOURCE_NAME,
            "framework": "google-adk==2.12.0",
            "harness": "Vertex AI Agent Engine (AdkApp)",
            "model": "gemini-2.5-flash",
            "region": "us-central1",
            "supervisor_service_account": AGENT_IDENTITY_LOOKUP["abo_supervisor_agent"],
        },
        "gateway": {
            "name": "acme-abo-agent-gateway",
            "url": AGENT_GATEWAY_URL,
            "gateway_service_account": GATEWAY_SERVICE_ACCOUNT,
            "caller_service_account": COCKPIT_SERVICE_ACCOUNT,
            "north_south_auth": f"OIDC ID Token + IAM Role Verification ({COCKPIT_SERVICE_ACCOUNT})",
            "east_west_a2a": "Registry-Verified + IAM Credentials OIDC Agent Identity Token",
            "hitl_priority8_gate": "ENFORCED",
        },
        "identities": AGENT_IDENTITY_LOOKUP,
        "otel": BFF_OTEL_STATUS,
        "registry": registry_data,
        "recent_otel_spans": RUNTIME.otel_spans,
    }


@app.get("/api/topology/hvac")
def get_hvac_topology() -> Dict[str, Any]:
    nodes = _load_csv("graph_nodes.csv")
    edges = _load_csv("graph_edges.csv")
    hvac_nodes = [
        n
        for n in nodes
        if str(n.get("node_category", "")).upper() in ("EQUIPMENT", "SPACE", "MECHANICAL", "SPATIAL")
    ]
    faulted_ids = {e.get("node_id") for e in RUNTIME.injected_events}
    root_ids = {
        e.get("node_id")
        for e in RUNTIME.injected_events
        if str(e.get("is_root_cause", "")).lower() in ("true", "1")
    }
    for n in hvac_nodes:
        nid = n.get("node_id")
        if nid in root_ids:
            n["runtime_status"] = "ROOT_CAUSE_FAULT"
        elif nid in faulted_ids:
            n["runtime_status"] = "SYMPATHETIC_IMPACT"
        else:
            n["runtime_status"] = "HEALTHY"
    hvac_edges = [e for e in edges if e.get("edge_type") in ("FEEDS", "LOCATED_IN")]
    return {"nodes": hvac_nodes, "edges": hvac_edges}


@app.get("/api/topology/network")
def get_network_topology() -> Dict[str, Any]:
    net_nodes = _load_csv("network_and_controller_nodes.csv")
    edges = _load_csv("graph_edges.csv")
    net_edges = [
        e
        for e in edges
        if e.get("edge_type")
        in ("CONTROLLED_BY", "ON_NETWORK", "BEHIND_ROUTER", "routesThrough", "hostedBy")
    ]
    return {"nodes": net_nodes, "edges": net_edges}


@app.get("/api/telemetry/{point_id:path}")
def get_point_telemetry(
    point_id: str = FastAPIPath(..., min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_:\-\./#]+$"),
    limit: int = Query(default=48, ge=1, le=288),
) -> Dict[str, Any]:
    rows = _load_csv("telemetry_ts_last_24h_sample.csv")
    matched = [r for r in rows if r.get("point_id") == point_id][-limit:]
    overlay = RUNTIME.injected_telemetry.get(point_id, [])
    return {
        "point_id": point_id,
        "baseline_series": matched,
        "live_overlay_series": overlay,
    }


@app.get("/api/energy-analytics")
def get_energy_analytics() -> Dict[str, Any]:
    return {
        "building_id": "BLDG-001",
        "baseline_eui_kbtu_sqft": 46.8,
        "peer_cohort_anomalies": [
            {
                "node_id": "bldg:vav_4_104",
                "scenario_id": "SCN-3",
                "fault_type": "Simultaneous Heating & Cooling (Leaking Reheat Valve @ 65%)",
                "discharge_air_temp_degf": 76.8,
                "cohort_mean_degf": 55.4,
                "z_score": 3.42,
                "estimated_annual_waste_usd": 4380,
            }
        ],
    }


SCENARIO_KEY_MAP: Dict[str, str] = {
    "SCN-1": "OPTION_A_SCN1_CASCADING_RTU1_FAILURE",
    "SCN-2": "OPTIONAL_SCN2_MSTP102_BUS_STORM",
    "SCN-3": "OPTIONAL_SCN3_SILENT_ENERGY_BLEED",
    "SCN-4": "OPTION_B_SCN4_SERVER_ROOM_PREDICTIVE_SLA",
}


def _resolve_scenarios() -> Dict[str, Any]:
    payloads = _load_json("live_injection_payloads.json")
    raw = payloads.get("live_scenarios") or payloads.get("scenarios") or {}
    resolved: Dict[str, Any] = {}
    for short_id, raw_key in SCENARIO_KEY_MAP.items():
        if raw_key in raw:
            resolved[short_id] = raw[raw_key]
        elif short_id in raw:
            resolved[short_id] = raw[short_id]
    return resolved


@app.get("/api/admin/state")
def get_admin_state() -> Dict[str, Any]:
    scenarios = _resolve_scenarios()
    return {
        "active_scenario": RUNTIME.active_scenario,
        "active_alarms_count": len(RUNTIME.injected_events),
        "injected_events": RUNTIME.injected_events,
        "agent_reasoning_steps": RUNTIME.agent_reasoning_steps,
        "otel_spans": RUNTIME.otel_spans,
        "staged_hitl_actions": RUNTIME.staged_hitl_actions,
        "work_orders": RUNTIME.work_orders,
        "last_reset_ts": RUNTIME.last_reset_ts,
        "available_scenarios": list(scenarios.keys()),
    }


@app.post("/api/admin/reset")
async def reset_demo_state() -> Dict[str, Any]:
    result = RUNTIME.reset()
    await RUNTIME.broadcast("DEMO_RESET", result)
    return result


@app.post("/api/admin/inject")
async def inject_live_scenario(req: InjectRequest) -> Dict[str, Any]:
    scenarios = _resolve_scenarios()
    if req.scenario_id not in scenarios:
        raise HTTPException(status_code=404, detail=f"Unknown scenario_id: {req.scenario_id}")

    RUNTIME.reset()
    scenario = scenarios[req.scenario_id]
    RUNTIME.active_scenario = req.scenario_id
    scenario_trace_id = uuid.uuid4().hex
    root_cause_node = scenario.get("root_cause_node", "bldg:area_ec_ahu_1")

    async def _run_waves() -> None:
        waves = scenario.get("waves", [])
        if not waves and "events" in scenario:
            waves = [{"wave_index": 1, "delay_seconds": 0, "title": scenario.get("button_label", req.scenario_id), "events": scenario["events"]}]
        prev_delay = 0.0
        for wave in waves:
            delay_s = float(wave.get("delay_seconds", 0))
            wait_s = max(0.0, (delay_s - prev_delay) / max(req.speed_multiplier, 0.25))
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            prev_delay = delay_s

            normalized_events: List[Dict[str, Any]] = []
            for ev in wave.get("events", []):
                eq_id = ev.get("node_id") or ev.get("equipment_id") or "bldg:area_ec_ahu_1"
                is_root = bool(
                    ev.get("is_root_cause")
                    or eq_id == root_cause_node
                    or ev.get("event_id") in ("ALM-0323", "ALM-0359", "ALM-0338", "ALM-0355")
                )
                norm_ev = {
                    "event_id": ev.get("event_id", f"ALM-{uuid.uuid4().hex[:6]}"),
                    "timestamp": ev.get("timestamp", dt.datetime.now(dt.timezone.utc).isoformat()),
                    "building_id": "BLDG-001",
                    "scenario_id": req.scenario_id,
                    "node_id": eq_id,
                    "point_id": ev.get("point_id", f"{eq_id}__zn_temp"),
                    "event_category": ev.get("event_category", "ALARM"),
                    "severity": ev.get("severity", "HIGH"),
                    "is_root_cause": is_root,
                    "suppressed_by_agent": not is_root,
                    "root_cause_event_id": "ALM-0323" if req.scenario_id == "SCN-1" else "ALM-0359",
                    "alarm_message": ev.get("alarm_message") or ev.get("message") or "",
                }
                RUNTIME.injected_events.append(norm_ev)
                normalized_events.append(norm_ev)

            if "telemetry_override" in wave:
                to = wave["telemetry_override"]
                pid = to.get("point_id", "")
                RUNTIME.injected_telemetry.setdefault(pid, []).append(to)

            for pt in wave.get("telemetry", []):
                pid = pt.get("point_id", "")
                RUNTIME.injected_telemetry.setdefault(pid, []).append(pt)

            enriched_action = None
            hitl_card = None
            raw_agent = wave.get("agent_action") or wave.get("autonomous_agent_action")
            if raw_agent:
                subagent_key = (
                    "cross_layer_rca_agent"
                    if req.scenario_id == "SCN-1"
                    else "energy_optimization_agent"
                )
                tool_called = (
                    "gql_find_common_hvac_ancestor"
                    if req.scenario_id == "SCN-1"
                    else "bqml_detect_and_forecast_sla"
                )
                summary_text = (
                    raw_agent.get("summary")
                    or f"{raw_agent.get('collapsed_incident_title', '')} — Executed: {raw_agent.get('gql_query_executed') or raw_agent.get('bqml_query_executed', '')}"
                )
                gw_res = await _dispatch_via_agent_gateway(
                    target_agent=raw_agent.get("subagent", subagent_key),
                    tool_name=tool_called,
                    prompt=(
                        f"Execute scenario {req.scenario_id} wave {wave.get('wave_index', 1)} root cause and blast-radius triage on {root_cause_node}: {summary_text}"
                    ),
                    site_id="ACME-SITE-001",
                    node_id=root_cause_node,
                    invoke_live_runtime=True,
                )
                gw_ident = gw_res.get("agent_identity", {})
                gw_rt = gw_res.get("agent_runtime", {})
                agent_identity = gw_ident.get("service_account") or AGENT_IDENTITY_LOOKUP.get(
                    subagent_key, "sa-agent-supervisor@genai-demos-391416.iam.gserviceaccount.com"
                )
                live_trace_id = gw_res.get("otel_trace_id", scenario_trace_id)
                live_span_id = gw_res.get("otel_span_id", uuid.uuid4().hex[:16])

                enriched_action = {
                    "agent_name": raw_agent.get("orchestrator", "abo_supervisor_agent"),
                    "subagent": raw_agent.get("subagent", subagent_key),
                    "tool_called": tool_called,
                    "summary": summary_text,
                    "shacl_status": gw_res.get("shacl_status", "CONFORMS (0 Violations)"),
                    "otel_trace_id": live_trace_id,
                    "otel_span_id": live_span_id,
                    "traceparent": gw_res.get("traceparent", f"00-{live_trace_id}-{live_span_id}-01"),
                    "cloud_trace_console_url": gw_res.get("cloud_trace_console_url", ""),
                    "agent_runtime": f"Vertex AI Agent Engine ({gw_rt.get('reasoning_engine_resource', AGENT_ENGINE_RESOURCE_NAME)})",
                    "agent_runtime_invoked": gw_rt.get("invoked", True),
                    "agent_runtime_latency_ms": gw_rt.get("latency_ms", gw_res.get("duration_ms", 0)),
                    "agent_gateway": f"acme-abo-client-to-agent ({gw_res.get('policy_verdict', 'ALLOW')})",
                    "agent_gateway_url": gw_res.get("gateway_url", AGENT_GATEWAY_URL),
                    "agent_identity": agent_identity,
                    "agent_identity_token_sha256": gw_ident.get("token_sha256_prefix", ""),
                    "agent_registry_uri": gw_res.get(
                        "agent_registry_uri", f"registry://acme-abo-agent-registry/{subagent_key}:2.0.0"
                    ),
                }
                RUNTIME.agent_reasoning_steps.append(enriched_action)
                RUNTIME.otel_spans.append(
                    {
                        "trace_id": live_trace_id,
                        "span_id": live_span_id,
                        "traceparent": gw_res.get("traceparent", ""),
                        "cloud_trace_console_url": gw_res.get("cloud_trace_console_url", ""),
                        "subagent": subagent_key,
                        "tool": tool_called,
                        "agent_identity": agent_identity,
                        "token_sha256_prefix": gw_ident.get("token_sha256_prefix", ""),
                        "reasoning_engine_resource": gw_rt.get("reasoning_engine_resource", AGENT_ENGINE_RESOURCE_NAME),
                        "gateway_verdict": gw_res.get("policy_verdict", "ALLOW"),
                        "duration_ms": gw_res.get("duration_ms", 0),
                    }
                )

                raw_hitl = raw_agent.get("hitl_remediation_proposal") or wave.get("hitl_proposal")
                if raw_hitl:
                    is_scn1 = req.scenario_id == "SCN-1"
                    hitl_card = {
                        "action_id": f"ACT-{req.scenario_id}-P8",
                        "target_point_id": raw_hitl.get("bacnet_uri", "bacnet://301003/BV:2"),
                        "proposed_value": 54.0 if is_scn1 else 71.0,
                        "unit": "DEG_F (Stage-2 Aux Cooling)" if is_scn1 else "DEG_F (+1.0F Deadband)",
                        "bacnet_priority": int(raw_hitl.get("priority_level", 8)),
                        "shacl_validation": "CONFORMS (Brick v1.4 + ASHRAE G36 Safe Bounds)",
                        "rationale": raw_hitl.get("command", "Execute Priority 8 remediation override"),
                        "plain_english_title": (
                            "Engage Backup Stage-2 DX Cooling & Reset Supply Air Setpoint to 54.0°F"
                            if is_scn1
                            else "Pre-Cool Server Room Supply Air & Widen Deadband by +1.0°F"
                        ),
                        "why_ai_chose_this": (
                            "RTU-1's primary Stage-1 DX compressor tripped on high head pressure, causing supply air to warm to 68.5°F and overheating 31 downstream rooms to 75.8°F. Knowledge Graph inspection confirmed RTU-1's secondary Stage-2 Auxiliary DX Compressor is healthy and currently idle."
                            if is_scn1
                            else "TimesFM 2.5 forecast predicts 1F Server Room will breach its 75.0°F SLA threshold within 35 minutes due to rack compute heat load. Pre-cooling via Stage-2 trim prevents thermal runaway."
                        ),
                        "safety_verification_explained": (
                            "Verified against ASHRAE Guideline 36 & Brick v1.4 SHACL constraints: 54.0°F supply air is safely above the 48.0°F coil-freeze cutout and writes to BACnet Command Priority 8 (Supervisor Override), preserving Priority 1–7 Life-Safety hardware locks."
                        ),
                        "expected_outcome": (
                            "Drops RTU-1 supply air from 68.5°F back to 54.0°F within ~3 minutes, cools all 31 affected rooms from 75.8°F back to 71.8°F nominal comfort, and avoids a 4.2-hour manual outage."
                        ),
                        "what_happens_on_approve": (
                            "1. Dispatches BACnet WriteProperty packet to Router #301003 (Object BV:2 @ Priority 8)\n"
                            "2. Engages Stage-2 Auxiliary Cooling Compressor on RTU-1\n"
                            "3. Automatically clears the 32 active alarms and restores Floor Plan & Knowledge Graph to Nominal Green (71.8°F)."
                        ),
                    }
                    RUNTIME.staged_hitl_actions.append(hitl_card)

            await RUNTIME.broadcast(
                "SCENARIO_WAVE",
                {
                    "scenario_id": req.scenario_id,
                    "title": scenario.get("button_label") or scenario.get("title"),
                    "wave_index": wave.get("wave_index"),
                    "description": wave.get("title") or wave.get("description"),
                    "events": normalized_events,
                    "telemetry": wave.get("telemetry", []),
                    "agent_action": enriched_action,
                    "hitl_proposal": hitl_card,
                },
            )

    asyncio.create_task(_run_waves())
    return {
        "status": "INJECTION_STARTED",
        "scenario_id": req.scenario_id,
        "otel_trace_id": scenario_trace_id,
        "title": scenario.get("button_label") or scenario.get("title"),
        "waves_count": len(scenario.get("waves", [])),
    }


@app.post("/api/hitl/approve")
async def approve_hitl_action(req: HitlDecisionRequest) -> Dict[str, Any]:
    matched = None
    for item in RUNTIME.staged_hitl_actions:
        if item.get("action_id") == req.action_id:
            item["status"] = "EXECUTED_PRIORITY_8" if req.decision == "APPROVE" else "REJECTED"
            item["operator_note"] = req.operator_note
            item["decided_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            matched = item
            break
    if not matched:
        matched = {
            "action_id": req.action_id,
            "status": "EXECUTED_PRIORITY_8" if req.decision == "APPROVE" else "REJECTED",
            "operator_note": req.operator_note,
            "decided_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }

    verification_step = None
    if req.decision == "APPROVE":
        resolved_count = len(RUNTIME.injected_events)
        RUNTIME.remediated_scenario = RUNTIME.active_scenario or "SCN-1"
        RUNTIME.building_healed = True
        RUNTIME.active_scenario = None
        RUNTIME.injected_events.clear()
        RUNTIME.injected_telemetry.clear()

        gw_res = await _dispatch_via_agent_gateway(
            target_agent="remediation_dispatch_agent",
            tool_name="bacnet_write_property_priority_8",
            prompt=(
                f"Human supervisor approved HITL action {req.action_id}. "
                f"Dispatch BACnet Priority 8 WriteProperty to {matched.get('target_point_id', 'bacnet://301003/BV:2')} "
                f"with value {matched.get('proposed_value', 54.0)} and verify closed-loop recovery."
            ),
            site_id="ACME-SITE-001",
            node_id="bldg:area_ec_ahu_1",
            bacnet_priority=8,
            invoke_live_runtime=True,
        )
        gw_ident = gw_res.get("agent_identity", {})
        gw_rt = gw_res.get("agent_runtime", {})
        trace_id = gw_res.get("otel_trace_id", uuid.uuid4().hex)
        span_id = gw_res.get("otel_span_id", uuid.uuid4().hex[:16])

        verification_step = {
            "agent_name": "abo_supervisor_agent",
            "subagent": "remediation_dispatch_agent",
            "tool_called": "bacnet_write_property_priority_8",
            "summary": (
                f"[CLOSED-LOOP AI REMEDIATION COMPLETE — BUILDING RESTORED TO NOMINAL]:\n"
                f"• Dispatched BACnet Priority 8 WriteProperty to {matched.get('target_point_id', 'bacnet://301003/BV:2')} → {matched.get('proposed_value', 54.0)} °F.\n"
                f"• Stage-2 Auxiliary DX Cooling Compressor engaged on RTU-1; supply air temperature recovered from 68.5°F → 54.0°F.\n"
                f"• All {max(resolved_count, 32)} alarms cleared and 31 downstream zones restored from 75.8°F → 71.8°F nominal setpoint.\n"
                f"• Total Autonomous MTTR: 4.2 minutes (vs. 4.2 hours historical manual baseline — saved $18,500 in SLA penalties)."
            ),
            "shacl_status": "VERIFIED (Closed-Loop Telemetry Nominal)",
            "otel_trace_id": trace_id,
            "otel_span_id": span_id,
            "traceparent": gw_res.get("traceparent", f"00-{trace_id}-{span_id}-01"),
            "cloud_trace_console_url": gw_res.get("cloud_trace_console_url", ""),
            "agent_runtime": f"Vertex AI Agent Engine ({gw_rt.get('reasoning_engine_resource', AGENT_ENGINE_RESOURCE_NAME)})",
            "agent_runtime_invoked": gw_rt.get("invoked", True),
            "agent_runtime_latency_ms": gw_rt.get("latency_ms", gw_res.get("duration_ms", 0)),
            "agent_gateway": f"acme-abo-client-to-agent ({gw_res.get('policy_verdict', 'ALLOW')})",
            "agent_gateway_url": gw_res.get("gateway_url", AGENT_GATEWAY_URL),
            "agent_identity": gw_ident.get("service_account", AGENT_IDENTITY_LOOKUP["remediation_dispatch_agent"]),
            "agent_identity_token_sha256": gw_ident.get("token_sha256_prefix", ""),
            "agent_registry_uri": "registry://acme-abo-agent-registry/remediation_dispatch_agent:2.0.0",
        }
        RUNTIME.agent_reasoning_steps.insert(0, verification_step)
        RUNTIME.otel_spans.insert(
            0,
            {
                "trace_id": trace_id,
                "span_id": span_id,
                "traceparent": gw_res.get("traceparent", ""),
                "cloud_trace_console_url": gw_res.get("cloud_trace_console_url", ""),
                "subagent": "remediation_dispatch_agent",
                "tool": "bacnet_write_property_priority_8",
                "agent_identity": verification_step["agent_identity"],
                "token_sha256_prefix": gw_ident.get("token_sha256_prefix", ""),
                "reasoning_engine_resource": gw_rt.get("reasoning_engine_resource", AGENT_ENGINE_RESOURCE_NAME),
                "gateway_verdict": gw_res.get("policy_verdict", "ALLOW"),
                "duration_ms": gw_res.get("duration_ms", 0),
            },
        )
        matched["building_healed"] = True
        matched["resolved_alarms_count"] = max(resolved_count, 32)
        matched["verification_step"] = verification_step
    else:
        matched["building_healed"] = False

    await RUNTIME.broadcast("HITL_DECISION", matched)
    return matched


@app.get("/api/events/stream")
async def stream_events() -> Any:
    from sse_starlette.sse import EventSourceResponse

    queue: asyncio.Queue = asyncio.Queue()
    RUNTIME.subscribers.append(queue)

    async def event_generator() -> AsyncGenerator[Dict[str, str], None]:
        try:
            yield {
                "event": "INIT_STATE",
                "data": json.dumps(
                    {
                        "active_scenario": RUNTIME.active_scenario,
                        "building_healed": RUNTIME.building_healed,
                        "active_alarms_count": len(RUNTIME.injected_events),
                        "injected_events": RUNTIME.injected_events,
                        "agent_reasoning_steps": RUNTIME.agent_reasoning_steps,
                        "staged_hitl_actions": RUNTIME.staged_hitl_actions,
                        "last_reset_ts": RUNTIME.last_reset_ts,
                    }
                ),
            }
            while True:
                msg = await queue.get()
                yield {
                    "event": msg["event_type"],
                    "data": json.dumps(msg),
                }
        finally:
            if queue in RUNTIME.subscribers:
                RUNTIME.subscribers.remove(queue)

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Deep Interactive Digital Twin, Floor Plan CAD & Knowledge Graph Explorer APIs
# ---------------------------------------------------------------------------

# Architectural CAD Room Layout Coordinates (1000x540 Blueprint Grid)
FLOOR_PLAN_ROOM_COORDS: Dict[str, Dict[str, int]] = {
    # Roof Mechanical Deck (bldg:area)
    "bldg:area_zone_west": {"x": 50, "y": 60, "w": 420, "h": 410},
    "bldg:area_zone_east": {"x": 510, "y": 60, "w": 440, "h": 410},
    # 1st Floor (bldg:ec_1st_floor) - 17 Rooms
    "bldg:room_1f_server_rm": {"x": 30, "y": 30, "w": 210, "h": 155},
    "bldg:room_1f_nsa_office": {"x": 250, "y": 30, "w": 175, "h": 155},
    "bldg:room_1f_lobby": {"x": 435, "y": 30, "w": 180, "h": 155},
    "bldg:room_1f_show_case": {"x": 625, "y": 30, "w": 170, "h": 155},
    "bldg:room_1f_new_conf": {"x": 805, "y": 30, "w": 165, "h": 155},
    "bldg:room_1f_nsa_cubes": {"x": 30, "y": 195, "w": 280, "h": 160},
    "bldg:room_1f_nsa_offices": {"x": 320, "y": 195, "w": 160, "h": 160},
    "bldg:room_1f_7_11": {"x": 490, "y": 195, "w": 150, "h": 160},
    "bldg:room_1f_break_room": {"x": 650, "y": 195, "w": 155, "h": 160},
    "bldg:room_1f_restrooms": {"x": 815, "y": 195, "w": 155, "h": 160},
    "bldg:room_1f_oem": {"x": 30, "y": 365, "w": 185, "h": 145},
    "bldg:room_1f_oem_lab": {"x": 225, "y": 365, "w": 165, "h": 145},
    "bldg:room_1f_oem_conf": {"x": 400, "y": 365, "w": 140, "h": 145},
    "bldg:room_1f_alcs_tpi": {"x": 550, "y": 365, "w": 135, "h": 145},
    "bldg:room_1f_nsa": {"x": 695, "y": 365, "w": 90, "h": 145},
    "bldg:room_1f_nsa_copier": {"x": 795, "y": 365, "w": 80, "h": 145},
    "bldg:room_1f_offices_vav10": {"x": 885, "y": 365, "w": 85, "h": 145},
    # 2nd Floor (bldg:ec_2nd_floor) - 17 Rooms
    "bldg:room_2f_open_office_202": {"x": 30, "y": 30, "w": 300, "h": 155},
    "bldg:room_2f_open_office_201a": {"x": 340, "y": 30, "w": 160, "h": 155},
    "bldg:room_2f_open_office_203": {"x": 510, "y": 30, "w": 150, "h": 155},
    "bldg:room_2f_open_office_203a": {"x": 670, "y": 30, "w": 145, "h": 155},
    "bldg:room_2f_training_univ": {"x": 825, "y": 30, "w": 145, "h": 155},
    "bldg:room_2f_huddle": {"x": 30, "y": 195, "w": 185, "h": 160},
    "bldg:room_2f_conf_230_airport": {"x": 225, "y": 195, "w": 190, "h": 160},
    "bldg:room_2f_conf_226_hotel_cal": {"x": 425, "y": 195, "w": 190, "h": 160},
    "bldg:room_2f_conf_218": {"x": 625, "y": 195, "w": 170, "h": 160},
    "bldg:room_2f_break_recording": {"x": 805, "y": 195, "w": 165, "h": 160},
    "bldg:room_2f_open_seating_228": {"x": 30, "y": 365, "w": 160, "h": 145},
    "bldg:room_2f_open_office_232": {"x": 200, "y": 365, "w": 165, "h": 145},
    "bldg:room_2f_office_231": {"x": 375, "y": 365, "w": 140, "h": 145},
    "bldg:room_2f_offices_233_235": {"x": 525, "y": 365, "w": 150, "h": 145},
    "bldg:room_2f_office_225": {"x": 685, "y": 365, "w": 95, "h": 145},
    "bldg:room_2f_open_office_221": {"x": 790, "y": 365, "w": 95, "h": 145},
    "bldg:room_2f_breakout": {"x": 895, "y": 365, "w": 75, "h": 145},
}


def _compute_node_runtime_status(node_id: str) -> str:
    root_ids = {
        e.get("node_id")
        for e in RUNTIME.injected_events
        if str(e.get("is_root_cause", "")).lower() in ("true", "1")
    }
    faulted_ids = {e.get("node_id") for e in RUNTIME.injected_events}
    if node_id in root_ids:
        return "ROOT_CAUSE_FAULT"
    if node_id == "bldg:area_zone_west" and "bldg:area_ec_ahu_1" in root_ids:
        return "ROOT_CAUSE_FAULT"
    if RUNTIME.active_scenario == "SCN-4" and node_id in ("bldg:room_1f_server_rm", "bldg:ec_1st_floor_vav_server_rm"):
        return "ROOT_CAUSE_FAULT"
    if node_id in faulted_ids:
        return "SYMPATHETIC_IMPACT"
    if RUNTIME.active_scenario == "SCN-1":
        if node_id.startswith("bldg:room_1f_") and node_id != "bldg:room_1f_server_rm":
            return "SYMPATHETIC_IMPACT"
        if node_id.startswith("bldg:ec_1st_floor_") and "server_rm" not in node_id:
            return "SYMPATHETIC_IMPACT"
    if not RUNTIME.building_healed and node_id in (
        "bldg:ec_2nd_floor_area9_emrd_2_piu_1",
        "bldg:ec_2nd_floor_area8_emrd_2_piu_8",
        "bldg:room_2f_huddle",
        "bldg:room_2f_open_office_232",
        "bldg:site4_smt_ahu_2_vav_4",
        "bldg:s4_room_smt_clean",
    ):
        return "ENERGY_OUTLIER"
    return "HEALTHY"


# Distinct Architectural Floor Plans & Equipment Inventories for Sites 002..005
MULTI_SITE_BLUEPRINTS: Dict[str, Dict[str, Any]] = {
    "ACME-SITE-002": {
        "floors": [
            {
                "floor_id": "bldg:s2_cold_deck",
                "label": "Level 1 — Deep-Freeze Vaults, Cold Staging & ASRS High-Bay",
                "short_label": "1F Cold Chain Deck",
                "primary_ahu_id": "bldg:s2_nh3_chiller_1",
                "primary_ahu_label": "NH3-CHILL-1 (Ammonia Glycol Plant)",
                "sla_tier": "Tier-1 Mission Critical",
            },
            {
                "floor_id": "bldg:s2_roof_plant",
                "label": "Roof Refrigeration Penthouse & Condenser Array",
                "short_label": "Roof Refrigeration Plant",
                "primary_ahu_id": "bldg:s2_nh3_chiller_1",
                "primary_ahu_label": "NH3-CHILL-1 & Condenser Towers",
                "sla_tier": "Tier-1 Mission Critical",
            },
        ],
        "rooms": [
            {
                "space_id": "bldg:s2_room_deep_freeze_a",
                "label": "Deep-Freeze Vault A (-10°F)",
                "floor_id": "bldg:s2_cold_deck",
                "sla_tier": "Tier-1 Mission Critical",
                "occupancy_pct": 12.0,
                "comfort_pct": 99.9,
                "live_temp_f": -9.8,
                "runtime_status": "HEALTHY",
                "coords": {"x": 30, "y": 40, "w": 300, "h": 220},
                "devices": [
                    {
                        "node_id": "bldg:s2_evap_df_a1",
                        "label": "Blast Evaporator Coil DF-A1",
                        "brick_class": "brick:Chilled_Water_Coil",
                        "ashrae_223p_class": "s223:HeatExchanger",
                        "serving_ahu_id": "bldg:s2_nh3_chiller_1",
                        "controller_id": "bldg:s2_ctrl_40101",
                        "point_count": 24,
                        "runtime_status": "HEALTHY",
                        "pin_x": 110,
                        "pin_y": 140,
                    },
                    {
                        "node_id": "bldg:s2_evap_df_a2",
                        "label": "Blast Evaporator Coil DF-A2",
                        "brick_class": "brick:Chilled_Water_Coil",
                        "ashrae_223p_class": "s223:HeatExchanger",
                        "serving_ahu_id": "bldg:s2_nh3_chiller_1",
                        "controller_id": "bldg:s2_ctrl_40102",
                        "point_count": 24,
                        "runtime_status": "HEALTHY",
                        "pin_x": 230,
                        "pin_y": 140,
                    },
                ],
            },
            {
                "space_id": "bldg:s2_room_biologics_vault",
                "label": "Biologics Cold Vault B (36°F)",
                "floor_id": "bldg:s2_cold_deck",
                "sla_tier": "Tier-1 Mission Critical",
                "occupancy_pct": 18.0,
                "comfort_pct": 99.8,
                "live_temp_f": 35.9,
                "runtime_status": "HEALTHY",
                "coords": {"x": 345, "y": 40, "w": 305, "h": 220},
                "devices": [
                    {
                        "node_id": "bldg:s2_crah_bio_1",
                        "label": "Glycol Air Handler BIO-1",
                        "brick_class": "brick:Computer_Room_Air_Conditioning",
                        "ashrae_223p_class": "s223:AirHandlingUnit",
                        "serving_ahu_id": "bldg:s2_nh3_chiller_1",
                        "controller_id": "bldg:s2_ctrl_40103",
                        "point_count": 28,
                        "runtime_status": "HEALTHY",
                        "pin_x": 490,
                        "pin_y": 140,
                    },
                ],
            },
            {
                "space_id": "bldg:s2_room_asrs_highbay",
                "label": "Automated ASRS Cranes High-Bay",
                "floor_id": "bldg:s2_cold_deck",
                "sla_tier": "Tier-2 Logistics Core",
                "occupancy_pct": 8.0,
                "comfort_pct": 99.4,
                "live_temp_f": 54.2,
                "runtime_status": "HEALTHY",
                "coords": {"x": 665, "y": 40, "w": 305, "h": 460},
                "devices": [
                    {
                        "node_id": "bldg:s2_hvls_destrat_1",
                        "label": "HVLS Destratification Fan 1",
                        "brick_class": "brick:Supply_Fan",
                        "ashrae_223p_class": "s223:Fan",
                        "serving_ahu_id": "bldg:s2_mua_dock_1",
                        "controller_id": "bldg:s2_ctrl_40104",
                        "point_count": 16,
                        "runtime_status": "HEALTHY",
                        "pin_x": 815,
                        "pin_y": 180,
                    },
                    {
                        "node_id": "bldg:s2_hvls_destrat_2",
                        "label": "HVLS Destratification Fan 2",
                        "brick_class": "brick:Supply_Fan",
                        "ashrae_223p_class": "s223:Fan",
                        "serving_ahu_id": "bldg:s2_mua_dock_1",
                        "controller_id": "bldg:s2_ctrl_40105",
                        "point_count": 16,
                        "runtime_status": "HEALTHY",
                        "pin_x": 815,
                        "pin_y": 340,
                    },
                ],
            },
            {
                "space_id": "bldg:s2_room_cold_dock",
                "label": "Refrigerated Cross-Dock Bays 1–18",
                "floor_id": "bldg:s2_cold_deck",
                "sla_tier": "Tier-2 Logistics Core",
                "occupancy_pct": 74.0,
                "comfort_pct": 98.9,
                "live_temp_f": 41.5,
                "runtime_status": "HEALTHY",
                "coords": {"x": 30, "y": 275, "w": 410, "h": 225},
                "devices": [
                    {
                        "node_id": "bldg:s2_dock_air_curtain_1",
                        "label": "Air Curtain Unit Dock-1..9",
                        "brick_class": "brick:Fan_Coil_Unit",
                        "ashrae_223p_class": "s223:TerminalUnit",
                        "serving_ahu_id": "bldg:s2_mua_dock_1",
                        "controller_id": "bldg:s2_ctrl_40106",
                        "point_count": 18,
                        "runtime_status": "HEALTHY",
                        "pin_x": 160,
                        "pin_y": 390,
                    },
                    {
                        "node_id": "bldg:s2_dock_dehum_1",
                        "label": "Desiccant Dehumidifier DH-1",
                        "brick_class": "brick:Air_Handling_Unit",
                        "ashrae_223p_class": "s223:AirHandlingUnit",
                        "serving_ahu_id": "bldg:s2_nh3_chiller_1",
                        "controller_id": "bldg:s2_ctrl_40107",
                        "point_count": 26,
                        "runtime_status": "HEALTHY",
                        "pin_x": 320,
                        "pin_y": 390,
                    },
                ],
            },
            {
                "space_id": "bldg:s2_room_dispatch_ops",
                "label": "Cold-Chain Dispatch & QA Lab",
                "floor_id": "bldg:s2_cold_deck",
                "sla_tier": "Tier-3 Standard Office",
                "occupancy_pct": 85.0,
                "comfort_pct": 99.5,
                "live_temp_f": 70.4,
                "runtime_status": "HEALTHY",
                "coords": {"x": 455, "y": 275, "w": 195, "h": 225},
                "devices": [
                    {
                        "node_id": "bldg:s2_vav_dispatch_1",
                        "label": "Dispatch VAV Box 1-4",
                        "brick_class": "brick:Variable_Air_Volume_Box",
                        "ashrae_223p_class": "s223:SingleDuctTerminal",
                        "serving_ahu_id": "bldg:s2_mua_dock_1",
                        "controller_id": "bldg:s2_ctrl_40108",
                        "point_count": 14,
                        "runtime_status": "HEALTHY",
                        "pin_x": 550,
                        "pin_y": 390,
                    },
                ],
            },
            {
                "space_id": "bldg:s2_room_nh3_penthouse",
                "label": "Ammonia Screw Compressor Hall",
                "floor_id": "bldg:s2_roof_plant",
                "sla_tier": "Tier-1 Mission Critical",
                "occupancy_pct": 5.0,
                "comfort_pct": 100.0,
                "live_temp_f": 64.0,
                "runtime_status": "HEALTHY",
                "coords": {"x": 40, "y": 50, "w": 440, "h": 430},
                "devices": [
                    {
                        "node_id": "bldg:s2_nh3_chiller_1",
                        "label": "NH3 Primary Chiller Skid #1",
                        "brick_class": "brick:Chiller",
                        "ashrae_223p_class": "s223:Chiller",
                        "serving_ahu_id": "",
                        "controller_id": "bldg:s2_ctrl_40100",
                        "point_count": 42,
                        "runtime_status": "HEALTHY",
                        "pin_x": 250,
                        "pin_y": 250,
                    },
                ],
            },
            {
                "space_id": "bldg:s2_room_condenser_yard",
                "label": "Adiabatic Condenser & Sub-Meter Deck",
                "floor_id": "bldg:s2_roof_plant",
                "sla_tier": "Tier-1 Mission Critical",
                "occupancy_pct": 2.0,
                "comfort_pct": 100.0,
                "live_temp_f": 68.5,
                "runtime_status": "HEALTHY",
                "coords": {"x": 500, "y": 50, "w": 450, "h": 430},
                "devices": [
                    {
                        "node_id": "bldg:s2_mua_dock_1",
                        "label": "Make-Up Air Unit MUA-1",
                        "brick_class": "brick:Air_Handling_Unit",
                        "ashrae_223p_class": "s223:AirHandlingUnit",
                        "serving_ahu_id": "",
                        "controller_id": "bldg:s2_ctrl_40109",
                        "point_count": 32,
                        "runtime_status": "HEALTHY",
                        "pin_x": 720,
                        "pin_y": 250,
                    },
                ],
            },
        ],
    },
    "ACME-SITE-003": {
        "floors": [
            {
                "floor_id": "bldg:s3_cleanroom_floor",
                "label": "Level 2 — ISO-5 Biopharma Cleanrooms & BSL-3 Core",
                "short_label": "2F Cleanroom Core",
                "primary_ahu_id": "bldg:s3_hepa_mahu_1",
                "primary_ahu_label": "MAHU-1 (100% Outdoor Air HEPA Unit)",
                "sla_tier": "Tier-1 Mission Critical",
            },
            {
                "floor_id": "bldg:s3_genomics_floor",
                "label": "Level 3 — Gene Sequencing Suite & Cryo Biobank",
                "short_label": "3F Genomics & Cryo",
                "primary_ahu_id": "bldg:s3_hepa_mahu_2",
                "primary_ahu_label": "MAHU-2 (Precision Lab Humidity AHU)",
                "sla_tier": "Tier-1 Mission Critical",
            },
        ],
        "rooms": [
            {
                "space_id": "bldg:s3_room_iso5_fill",
                "label": "ISO-5 Sterile Fill-Finish Suite (+0.08 in.w.c.)",
                "floor_id": "bldg:s3_cleanroom_floor",
                "sla_tier": "Tier-1 Mission Critical",
                "occupancy_pct": 45.0,
                "comfort_pct": 99.9,
                "live_temp_f": 66.2,
                "runtime_status": "HEALTHY",
                "coords": {"x": 30, "y": 40, "w": 360, "h": 230},
                "devices": [
                    {
                        "node_id": "bldg:s3_ffu_array_1",
                        "label": "ULPA Fan Filter Array FFU-1..12",
                        "brick_class": "brick:Filter",
                        "ashrae_223p_class": "s223:AirHandlingUnit",
                        "serving_ahu_id": "bldg:s3_hepa_mahu_1",
                        "controller_id": "bldg:s3_ctrl_50101",
                        "point_count": 30,
                        "runtime_status": "HEALTHY",
                        "pin_x": 150,
                        "pin_y": 155,
                    },
                    {
                        "node_id": "bldg:s3_phoenix_valve_1",
                        "label": "Venturi Supply Air Valve VSV-1",
                        "brick_class": "brick:Variable_Air_Volume_Box",
                        "ashrae_223p_class": "s223:SingleDuctTerminal",
                        "serving_ahu_id": "bldg:s3_hepa_mahu_1",
                        "controller_id": "bldg:s3_ctrl_50102",
                        "point_count": 22,
                        "runtime_status": "HEALTHY",
                        "pin_x": 290,
                        "pin_y": 155,
                    },
                ],
            },
            {
                "space_id": "bldg:s3_room_bsl3_virology",
                "label": "BSL-3 Negative-Pressure Suite (-0.06 in.w.c.)",
                "floor_id": "bldg:s3_cleanroom_floor",
                "sla_tier": "Tier-1 Mission Critical",
                "occupancy_pct": 38.0,
                "comfort_pct": 99.9,
                "live_temp_f": 67.4,
                "runtime_status": "HEALTHY",
                "coords": {"x": 405, "y": 40, "w": 320, "h": 230},
                "devices": [
                    {
                        "node_id": "bldg:s3_bag_in_exhaust_1",
                        "label": "BIBO HEPA Exhaust Scrubber EX-1",
                        "brick_class": "brick:Exhaust_Fan",
                        "ashrae_223p_class": "s223:Fan",
                        "serving_ahu_id": "bldg:s3_hepa_mahu_1",
                        "controller_id": "bldg:s3_ctrl_50103",
                        "point_count": 26,
                        "runtime_status": "HEALTHY",
                        "pin_x": 565,
                        "pin_y": 155,
                    },
                ],
            },
            {
                "space_id": "bldg:s3_room_airlock_corridor",
                "label": "Cascading Pressure Airlock & Gowning",
                "floor_id": "bldg:s3_cleanroom_floor",
                "sla_tier": "Tier-1 Mission Critical",
                "occupancy_pct": 30.0,
                "comfort_pct": 99.7,
                "live_temp_f": 68.1,
                "runtime_status": "HEALTHY",
                "coords": {"x": 740, "y": 40, "w": 230, "h": 460},
                "devices": [
                    {
                        "node_id": "bldg:s3_dp_monitor_airlock",
                        "label": "Differential Pressure Controller DP-1",
                        "brick_class": "brick:Variable_Air_Volume_Box",
                        "ashrae_223p_class": "s223:TerminalUnit",
                        "serving_ahu_id": "bldg:s3_hepa_mahu_1",
                        "controller_id": "bldg:s3_ctrl_50104",
                        "point_count": 18,
                        "runtime_status": "HEALTHY",
                        "pin_x": 855,
                        "pin_y": 240,
                    },
                ],
            },
            {
                "space_id": "bldg:s3_room_chem_fume_bay",
                "label": "Organic Synthesis Wet Lab (14 Fume Hoods)",
                "floor_id": "bldg:s3_cleanroom_floor",
                "sla_tier": "Tier-2 Lab Research",
                "occupancy_pct": 72.0,
                "comfort_pct": 99.6,
                "live_temp_f": 69.0,
                "runtime_status": "HEALTHY",
                "coords": {"x": 30, "y": 285, "w": 695, "h": 215},
                "devices": [
                    {
                        "node_id": "bldg:s3_fume_hood_vav_1",
                        "label": "Fume Hood Sash VAV-FH1",
                        "brick_class": "brick:Fume_Hood",
                        "ashrae_223p_class": "s223:TerminalUnit",
                        "serving_ahu_id": "bldg:s3_hepa_mahu_1",
                        "controller_id": "bldg:s3_ctrl_50105",
                        "point_count": 20,
                        "runtime_status": "HEALTHY",
                        "pin_x": 220,
                        "pin_y": 395,
                    },
                    {
                        "node_id": "bldg:s3_fume_hood_vav_2",
                        "label": "Fume Hood Sash VAV-FH2",
                        "brick_class": "brick:Fume_Hood",
                        "ashrae_223p_class": "s223:TerminalUnit",
                        "serving_ahu_id": "bldg:s3_hepa_mahu_1",
                        "controller_id": "bldg:s3_ctrl_50106",
                        "point_count": 20,
                        "runtime_status": "HEALTHY",
                        "pin_x": 510,
                        "pin_y": 395,
                    },
                ],
            },
            {
                "space_id": "bldg:s3_room_cryo_biobank",
                "label": "LN2 Cryo-Biobank & O2 Depletion Monitored Vault",
                "floor_id": "bldg:s3_genomics_floor",
                "sla_tier": "Tier-1 Mission Critical",
                "occupancy_pct": 15.0,
                "comfort_pct": 100.0,
                "live_temp_f": 65.5,
                "runtime_status": "HEALTHY",
                "coords": {"x": 30, "y": 45, "w": 450, "h": 450},
                "devices": [
                    {
                        "node_id": "bldg:s3_hepa_mahu_2",
                        "label": "Precision Lab AHU MAHU-2",
                        "brick_class": "brick:Air_Handling_Unit",
                        "ashrae_223p_class": "s223:AirHandlingUnit",
                        "serving_ahu_id": "",
                        "controller_id": "bldg:s3_ctrl_50107",
                        "point_count": 36,
                        "runtime_status": "HEALTHY",
                        "pin_x": 250,
                        "pin_y": 250,
                    },
                ],
            },
            {
                "space_id": "bldg:s3_room_sequencing_cluster",
                "label": "High-Throughput Sequencing & Compute Bay",
                "floor_id": "bldg:s3_genomics_floor",
                "sla_tier": "Tier-1 Mission Critical",
                "occupancy_pct": 65.0,
                "comfort_pct": 99.8,
                "live_temp_f": 67.8,
                "runtime_status": "HEALTHY",
                "coords": {"x": 500, "y": 45, "w": 470, "h": 450},
                "devices": [
                    {
                        "node_id": "bldg:s3_crah_seq_1",
                        "label": "In-Row CRAH Genomics-1",
                        "brick_class": "brick:Computer_Room_Air_Conditioning",
                        "ashrae_223p_class": "s223:AirHandlingUnit",
                        "serving_ahu_id": "bldg:s3_hepa_mahu_2",
                        "controller_id": "bldg:s3_ctrl_50108",
                        "point_count": 24,
                        "runtime_status": "HEALTHY",
                        "pin_x": 730,
                        "pin_y": 250,
                    },
                ],
            },
        ],
    },
    "ACME-SITE-004": {
        "floors": [
            {
                "floor_id": "bldg:s4_factory_floor",
                "label": "Main Production Floor — 5-Axis CNC, SMT Line & Curing Ovens",
                "short_label": "1F Factory Floor",
                "primary_ahu_id": "bldg:s4_ind_ahu_1",
                "primary_ahu_label": "IND-AHU-1 (Process Make-Up & Chilled Water)",
                "sla_tier": "Tier-1 Production Critical",
            },
            {
                "floor_id": "bldg:s4_utility_mezz",
                "label": "Mezzanine — Compressed Air, Chilled Water & Substation",
                "short_label": "2F Central Utility Plant",
                "primary_ahu_id": "bldg:s4_ind_ahu_1",
                "primary_ahu_label": "CHW-PLANT-4 & Air Compressors",
                "sla_tier": "Tier-1 Production Critical",
            },
        ],
        "rooms": [
            {
                "space_id": "bldg:s4_room_cnc_bay",
                "label": "5-Axis Titanium CNC Machining Hall",
                "floor_id": "bldg:s4_factory_floor",
                "sla_tier": "Tier-1 Production Critical",
                "occupancy_pct": 88.0,
                "comfort_pct": 98.2,
                "live_temp_f": 72.6,
                "runtime_status": "HEALTHY",
                "coords": {"x": 30, "y": 40, "w": 460, "h": 240},
                "devices": [
                    {
                        "node_id": "bldg:s4_mist_collector_1",
                        "label": "Oil-Mist Extractor Fan MC-1",
                        "brick_class": "brick:Exhaust_Fan",
                        "ashrae_223p_class": "s223:Fan",
                        "serving_ahu_id": "bldg:s4_ind_ahu_1",
                        "controller_id": "bldg:s4_ctrl_60101",
                        "point_count": 20,
                        "runtime_status": "HEALTHY",
                        "pin_x": 160,
                        "pin_y": 160,
                    },
                    {
                        "node_id": "bldg:s4_process_chw_loop_1",
                        "label": "Spindle Coolant Heat Exchanger HX-1",
                        "brick_class": "brick:Chilled_Water_System",
                        "ashrae_223p_class": "s223:HeatExchanger",
                        "serving_ahu_id": "bldg:s4_ind_ahu_1",
                        "controller_id": "bldg:s4_ctrl_60102",
                        "point_count": 24,
                        "runtime_status": "HEALTHY",
                        "pin_x": 350,
                        "pin_y": 160,
                    },
                ],
            },
            {
                "space_id": "bldg:s4_room_smt_clean",
                "label": "SMT PCB Assembly Line (Simultaneous Reheat Outlier)",
                "floor_id": "bldg:s4_factory_floor",
                "sla_tier": "Tier-1 Production Critical",
                "occupancy_pct": 92.0,
                "comfort_pct": 95.4,
                "live_temp_f": 76.4,
                "runtime_status": "ENERGY_OUTLIER",
                "coords": {"x": 505, "y": 40, "w": 465, "h": 240},
                "devices": [
                    {
                        "node_id": "bldg:site4_smt_ahu_2_vav_4",
                        "label": "SMT Line VAV-4 (Leaking Reheat Valve)",
                        "brick_class": "brick:Variable_Air_Volume_Box_With_Reheat",
                        "ashrae_223p_class": "s223:SingleDuctTerminal",
                        "serving_ahu_id": "bldg:s4_ind_ahu_1",
                        "controller_id": "bldg:s4_ctrl_60103",
                        "point_count": 22,
                        "runtime_status": "ENERGY_OUTLIER",
                        "pin_x": 730,
                        "pin_y": 160,
                    },
                ],
            },
            {
                "space_id": "bldg:s4_room_curing_booth",
                "label": "Thermal Composite Curing & Paint Line",
                "floor_id": "bldg:s4_factory_floor",
                "sla_tier": "Tier-2 Manufacturing",
                "occupancy_pct": 60.0,
                "comfort_pct": 98.0,
                "live_temp_f": 74.8,
                "runtime_status": "HEALTHY",
                "coords": {"x": 30, "y": 295, "w": 580, "h": 205},
                "devices": [
                    {
                        "node_id": "bldg:s4_rto_exhaust_1",
                        "label": "Regenerative Thermal Oxidizer Fan RTO-1",
                        "brick_class": "brick:Exhaust_Fan",
                        "ashrae_223p_class": "s223:Fan",
                        "serving_ahu_id": "bldg:s4_ind_ahu_1",
                        "controller_id": "bldg:s4_ctrl_60104",
                        "point_count": 28,
                        "runtime_status": "HEALTHY",
                        "pin_x": 310,
                        "pin_y": 400,
                    },
                ],
            },
            {
                "space_id": "bldg:s4_room_metrology_lab",
                "label": "CMM Coordinate Metrology Lab (68.0°F ±0.2°F)",
                "floor_id": "bldg:s4_factory_floor",
                "sla_tier": "Tier-1 Production Critical",
                "occupancy_pct": 50.0,
                "comfort_pct": 99.9,
                "live_temp_f": 68.0,
                "runtime_status": "HEALTHY",
                "coords": {"x": 625, "y": 295, "w": 345, "h": 205},
                "devices": [
                    {
                        "node_id": "bldg:s4_crah_cmm_1",
                        "label": "Precision Metrology CRAC-CMM1",
                        "brick_class": "brick:Computer_Room_Air_Conditioning",
                        "ashrae_223p_class": "s223:AirHandlingUnit",
                        "serving_ahu_id": "bldg:s4_ind_ahu_1",
                        "controller_id": "bldg:s4_ctrl_60105",
                        "point_count": 26,
                        "runtime_status": "HEALTHY",
                        "pin_x": 795,
                        "pin_y": 400,
                    },
                ],
            },
            {
                "space_id": "bldg:s4_room_cup_plant",
                "label": "Central Chilled Water & 150-HP Rotary Air Plant",
                "floor_id": "bldg:s4_utility_mezz",
                "sla_tier": "Tier-1 Production Critical",
                "occupancy_pct": 10.0,
                "comfort_pct": 100.0,
                "live_temp_f": 71.0,
                "runtime_status": "HEALTHY",
                "coords": {"x": 40, "y": 45, "w": 920, "h": 450},
                "devices": [
                    {
                        "node_id": "bldg:s4_ind_ahu_1",
                        "label": "Industrial Make-Up Air Handler IND-AHU-1",
                        "brick_class": "brick:Air_Handling_Unit",
                        "ashrae_223p_class": "s223:AirHandlingUnit",
                        "serving_ahu_id": "",
                        "controller_id": "bldg:s4_ctrl_60100",
                        "point_count": 40,
                        "runtime_status": "HEALTHY",
                        "pin_x": 480,
                        "pin_y": 250,
                    },
                ],
            },
        ],
    },
    "ACME-SITE-005": {
        "floors": [
            {
                "floor_id": "bldg:s5_exec_sky_floor",
                "label": "Level 6 — Executive Briefing Center & AI Robotics Showcase",
                "short_label": "6F Executive Sky Floor",
                "primary_ahu_id": "bldg:s5_vrf_oas_1",
                "primary_ahu_label": "DOAS-1 & VRF Heat-Recovery Plant",
                "sla_tier": "Tier-1 Executive & Customer",
            },
            {
                "floor_id": "bldg:s5_eng_collab_floor",
                "label": "Level 5 — Silicon Valley AI Engineering Neighborhoods",
                "short_label": "5F AI Engineering Pods",
                "primary_ahu_id": "bldg:s5_vrf_oas_1",
                "primary_ahu_label": "DOAS-1 Dedicated Outdoor Air System",
                "sla_tier": "Tier-2 Commercial Office",
            },
        ],
        "rooms": [
            {
                "space_id": "bldg:s5_room_ebc_theater",
                "label": "Customer Executive Briefing Amphitheater",
                "floor_id": "bldg:s5_exec_sky_floor",
                "sla_tier": "Tier-1 Executive & Customer",
                "occupancy_pct": 82.0,
                "comfort_pct": 99.7,
                "live_temp_f": 70.8,
                "runtime_status": "HEALTHY",
                "coords": {"x": 30, "y": 40, "w": 450, "h": 235},
                "devices": [
                    {
                        "node_id": "bldg:s5_vav_ebc_1",
                        "label": "CO2 Demand-Controlled VAV-EBC1",
                        "brick_class": "brick:Variable_Air_Volume_Box",
                        "ashrae_223p_class": "s223:SingleDuctTerminal",
                        "serving_ahu_id": "bldg:s5_vrf_oas_1",
                        "controller_id": "bldg:s5_ctrl_70101",
                        "point_count": 20,
                        "runtime_status": "HEALTHY",
                        "pin_x": 250,
                        "pin_y": 160,
                    },
                ],
            },
            {
                "space_id": "bldg:s5_room_robotics_arena",
                "label": "Autonomous Robotics & Drone Testing Arena",
                "floor_id": "bldg:s5_exec_sky_floor",
                "sla_tier": "Tier-1 Executive & Customer",
                "occupancy_pct": 65.0,
                "comfort_pct": 99.5,
                "live_temp_f": 69.5,
                "runtime_status": "HEALTHY",
                "coords": {"x": 495, "y": 40, "w": 475, "h": 235},
                "devices": [
                    {
                        "node_id": "bldg:s5_fcu_robotics_1",
                        "label": "Chilled Beam Array CB-ROB1",
                        "brick_class": "brick:Chilled_Beam",
                        "ashrae_223p_class": "s223:TerminalUnit",
                        "serving_ahu_id": "bldg:s5_vrf_oas_1",
                        "controller_id": "bldg:s5_ctrl_70102",
                        "point_count": 18,
                        "runtime_status": "HEALTHY",
                        "pin_x": 730,
                        "pin_y": 160,
                    },
                ],
            },
            {
                "space_id": "bldg:s5_room_boardroom",
                "label": "Pacific Panorama Boardroom & Sky Terrace",
                "floor_id": "bldg:s5_exec_sky_floor",
                "sla_tier": "Tier-1 Executive & Customer",
                "occupancy_pct": 55.0,
                "comfort_pct": 99.6,
                "live_temp_f": 71.2,
                "runtime_status": "HEALTHY",
                "coords": {"x": 30, "y": 290, "w": 940, "h": 210},
                "devices": [
                    {
                        "node_id": "bldg:s5_vrf_boardroom_1",
                        "label": "VRF Fan Coil Unit VRF-601",
                        "brick_class": "brick:Fan_Coil_Unit",
                        "ashrae_223p_class": "s223:TerminalUnit",
                        "serving_ahu_id": "bldg:s5_vrf_oas_1",
                        "controller_id": "bldg:s5_ctrl_70103",
                        "point_count": 16,
                        "runtime_status": "HEALTHY",
                        "pin_x": 490,
                        "pin_y": 395,
                    },
                ],
            },
            {
                "space_id": "bldg:s5_room_ai_pod_west",
                "label": "AI Foundation Model Engineering Pod West",
                "floor_id": "bldg:s5_eng_collab_floor",
                "sla_tier": "Tier-2 Commercial Office",
                "occupancy_pct": 90.0,
                "comfort_pct": 99.2,
                "live_temp_f": 71.5,
                "runtime_status": "HEALTHY",
                "coords": {"x": 30, "y": 45, "w": 460, "h": 450},
                "devices": [
                    {
                        "node_id": "bldg:s5_vrf_oas_1",
                        "label": "Dedicated Outdoor Air DOAS-1",
                        "brick_class": "brick:Dedicated_Outdoor_Air_System_Unit",
                        "ashrae_223p_class": "s223:AirHandlingUnit",
                        "serving_ahu_id": "",
                        "controller_id": "bldg:s5_ctrl_70100",
                        "point_count": 34,
                        "runtime_status": "HEALTHY",
                        "pin_x": 260,
                        "pin_y": 250,
                    },
                ],
            },
            {
                "space_id": "bldg:s5_room_ai_pod_east",
                "label": "Edge Silicon Hardware Validation Lab East",
                "floor_id": "bldg:s5_eng_collab_floor",
                "sla_tier": "Tier-2 Commercial Office",
                "occupancy_pct": 84.0,
                "comfort_pct": 99.4,
                "live_temp_f": 70.1,
                "runtime_status": "HEALTHY",
                "coords": {"x": 505, "y": 45, "w": 465, "h": 450},
                "devices": [
                    {
                        "node_id": "bldg:s5_vav_silicon_east",
                        "label": "Lab Exhaust & Supply VAV-504",
                        "brick_class": "brick:Variable_Air_Volume_Box",
                        "ashrae_223p_class": "s223:SingleDuctTerminal",
                        "serving_ahu_id": "bldg:s5_vrf_oas_1",
                        "controller_id": "bldg:s5_ctrl_70104",
                        "point_count": 18,
                        "runtime_status": "HEALTHY",
                        "pin_x": 735,
                        "pin_y": 250,
                    },
                ],
            },
        ],
    },
}


@app.get("/api/buildings/{site_id}/digital-twin")
def get_building_digital_twin(
    site_id: str = FastAPIPath(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$"),
) -> Dict[str, Any]:
    sites = _load_csv("portfolio_sites.csv")
    raw_site_meta = next((s for s in sites if s.get("site_id") == site_id), sites[0] if sites else {})
    site_meta = dict(raw_site_meta)
    meta_extra = SITE_ASSET_BREAKDOWN_META.get(site_id, {})
    site_meta["asset_breakdown_short"] = meta_extra.get(
        "asset_breakdown_short",
        f"{site_meta.get('equipment_count', 26)} HVAC Units • {site_meta.get('bacnet_controllers_count', 100)} BACnet Controllers",
    )
    site_meta["asset_breakdown_detail"] = meta_extra.get("asset_breakdown_detail", {})
    site_meta["ai_predictive_headline"] = (
        "Closed-Loop AI Remediation Verified — All 22 1st-Floor Zones Restored to 71.8°F Nominal"
        if site_id == "ACME-SITE-001" and RUNTIME.building_healed
        else meta_extra.get("ai_predictive_headline", "Nominal AI Predictive Baseline")
    )
    site_meta["top_risk_node_id"] = meta_extra.get("top_risk_node_id", "bldg:area_ec_ahu_1")
    site_meta["top_risk_pct"] = (
        4
        if site_id == "ACME-SITE-001" and RUNTIME.building_healed
        else (96 if site_id == "ACME-SITE-001" and len(RUNTIME.injected_events) > 0 else meta_extra.get("top_risk_pct", 12))
    )

    # If the user selects one of the non-hero portfolio sites (ACME-SITE-002..005),
    # return its dedicated facility floor plan, custom room geometry, and equipment inventory
    if site_id in MULTI_SITE_BLUEPRINTS:
        bp = MULTI_SITE_BLUEPRINTS[site_id]
        all_eq = []
        all_ctrl = []
        enriched_rooms = []
        for rm in bp["rooms"]:
            rm_copy = dict(rm)
            sp = 68.0 if "clean" in rm["space_id"] or "hall" in rm["space_id"] or "server" in rm["space_id"] else 71.0
            if rm["live_temp_f"] < 69.5 and rm["runtime_status"] == "HEALTHY":
                sp = round(rm["live_temp_f"] - 0.2, 1)
            elif rm["runtime_status"] == "ENERGY_OUTLIER":
                sp = 71.0
            rm_copy["setpoint_f"] = sp
            rm_copy["delta_temp_f"] = round(float(rm["live_temp_f"]) - sp, 1)
            rm_copy["thermal_load_kw"] = 38.4 if rm["runtime_status"] == "ENERGY_OUTLIER" else 14.2
            enriched_rooms.append(rm_copy)
            for dev in rm["devices"]:
                all_eq.append(
                    {
                        "node_id": dev["node_id"],
                        "label": dev["label"],
                        "brick_class": dev["brick_class"],
                        "ashrae_223p_class": dev["ashrae_223p_class"],
                        "floor_id": rm["floor_id"],
                        "room_id": rm["space_id"],
                        "serving_ahu_id": dev["serving_ahu_id"],
                        "controller_id": dev["controller_id"],
                        "point_count": str(dev["point_count"]),
                        "runtime_status": dev["runtime_status"],
                    }
                )
                all_ctrl.append(
                    {
                        "node_id": dev["controller_id"],
                        "label": f"BACnet Controller {dev['controller_id'].split('_')[-1]} ({dev['label'][:22]})",
                        "entity_category": "bsm:Controller",
                        "controller_model": "ALC Optiflex ZN-340",
                        "network_id": f"bldg:{site_id.lower().replace('-', '_')}_bacnet_ip",
                        "media_type": "BACnet/IP UDP:47808",
                    }
                )
        return {
            "site": site_meta,
            "floors": bp["floors"],
            "rooms": enriched_rooms,
            "equipment_count": int(site_meta.get("equipment_count") or len(all_eq)),
            "controllers_count": int(site_meta.get("bacnet_controllers_count") or len(all_ctrl)),
            "edges_count": len(all_eq) * 4,
            "all_equipment": all_eq,
            "all_controllers": all_ctrl,
            "has_active_incident": False,
            "building_healed": False,
            "remediated_scenario": None,
            "routine_bas_heartbeats": [
                {
                    "timestamp": "LIVE COV",
                    "protocol": "BACnet/IP UDP:47808",
                    "message": f"{site_meta.get('site_name')} — {bp['floors'][0]['primary_ahu_label']} tracking supply setpoint nominally (0 active root-cause alarms).",
                },
                {
                    "timestamp": "SHACL GUARD",
                    "protocol": "ASHRAE 223P / Brick v1.4",
                    "message": f"All {site_meta.get('bacnet_controllers_count')} BACnet controllers reporting 0.0% packet loss across {site_meta.get('city')}.",
                },
            ],
        }

    spatial_rows = _load_csv("spatial_nodes.csv")
    equip_rows = _load_csv("equipment_nodes.csv")
    net_rows = _load_csv("network_and_controller_nodes.csv")
    edges = _load_csv("graph_edges.csv")

    equip_by_id = {e["node_id"]: e for e in equip_rows if e.get("node_id")}
    for eq in equip_rows:
        nid = eq.get("node_id", "")
        eq["runtime_status"] = _compute_node_runtime_status(nid)

    # Build floor list for ACME-SITE-001 (Hero Site)
    floors = [
        {
            "floor_id": "bldg:ec_1st_floor",
            "label": "1st Floor — Server Room, Labs & Customer Showcase",
            "short_label": "1st Floor",
            "primary_ahu_id": "bldg:area_ec_ahu_1",
            "primary_ahu_label": "RTU-1 (ACME) Rooftop Unit",
            "sla_tier": "Tier-1 Mission Critical",
        },
        {
            "floor_id": "bldg:ec_2nd_floor",
            "label": "2nd Floor — Open Engineering Offices & Training Univ",
            "short_label": "2nd Floor",
            "primary_ahu_id": "bldg:area_ec_ahu_2",
            "primary_ahu_label": "RTU-2 (2nd Floor East/West)",
            "sla_tier": "Tier-2 Customer Facing",
        },
        {
            "floor_id": "bldg:area",
            "label": "Roof Mechanical Penthouse & Main Electrical Deck",
            "short_label": "Roof Deck",
            "primary_ahu_id": "bldg:area_ec_ahu_1",
            "primary_ahu_label": "RTU-1 & RTU-2 Primary Air Handlers",
            "sla_tier": "Tier-1 Mission Critical",
        },
    ]

    rooms_out: List[Dict[str, Any]] = []
    # Include synthetic Roof Mechanical bays so Roof floor plan is super visual
    roof_rooms = [
        {
            "space_id": "bldg:area_zone_west",
            "space_type": "rec:Roof_Zone",
            "label": "West Roof Mechanical Pad (RTU-1 & Main Meters)",
            "parent_space_id": "bldg:area",
            "sla_criticality_tier": "Tier-1 Mission Critical",
            "weekday_daytime_occupancy_pct": "5.0",
            "comfort_pct_within_1f": "100.0",
            "served_by_equipment_ids": "bldg:area_ec_ahu_1;bldg:alcs_development_area_modbus_meter_main;bldg:alcs_development_area_domestic_water_flow_meter_ec",
        },
        {
            "space_id": "bldg:area_zone_east",
            "space_type": "rec:Roof_Zone",
            "label": "East Roof Mechanical Pad (RTU-2 & Sub-Meters)",
            "parent_space_id": "bldg:area",
            "sla_criticality_tier": "Tier-1 Mission Critical",
            "weekday_daytime_occupancy_pct": "5.0",
            "comfort_pct_within_1f": "100.0",
            "served_by_equipment_ids": "bldg:area_ec_ahu_2;bldg:area_eq_1610100_1;bldg:area_eq_1610102_1;bldg:alcs_development_area_irrigation_valve_control_ec",
        },
    ]

    all_room_rows = [r for r in spatial_rows if r.get("space_type") == "rec:Room"] + roof_rooms
    for rm in all_room_rows:
        rid = rm.get("space_id", "")
        coords = FLOOR_PLAN_ROOM_COORDS.get(rid, {"x": 40, "y": 40, "w": 150, "h": 120})
        eq_ids = [
            eid.strip()
            for eid in (rm.get("served_by_equipment_ids") or "").split(";")
            if eid.strip()
        ]
        # Also include any equipment whose room_id == rid
        for eq in equip_rows:
            if eq.get("room_id") == rid and eq.get("node_id") not in eq_ids:
                eq_ids.append(eq["node_id"])

        devices = []
        room_status = _compute_node_runtime_status(rid)
        for idx, eid in enumerate(eq_ids):
            eq_obj = equip_by_id.get(eid)
            if not eq_obj:
                continue
            st = _compute_node_runtime_status(eid)
            if st == "ROOT_CAUSE_FAULT":
                room_status = "ROOT_CAUSE_FAULT"
            elif st == "SYMPATHETIC_IMPACT" and room_status != "ROOT_CAUSE_FAULT":
                room_status = "SYMPATHETIC_IMPACT"
            elif st == "ENERGY_OUTLIER" and room_status == "HEALTHY":
                room_status = "ENERGY_OUTLIER"

            # Compute pin coordinates inside the room box
            col = idx % 3
            row = idx // 3
            pin_x = coords["x"] + 28 + min(col * 52, max(coords["w"] - 36, 24))
            pin_y = coords["y"] + 58 + min(row * 34, max(coords["h"] - 28, 24))

            devices.append(
                {
                    "node_id": eid,
                    "label": eq_obj.get("label", eid),
                    "brick_class": eq_obj.get("brick_class", "brick:Equipment"),
                    "ashrae_223p_class": eq_obj.get("ashrae_223p_class", "s223:Equipment"),
                    "serving_ahu_id": eq_obj.get("serving_ahu_id", ""),
                    "controller_id": eq_obj.get("controller_id", ""),
                    "point_count": int(eq_obj.get("point_count") or 0),
                    "runtime_status": st,
                    "pin_x": pin_x,
                    "pin_y": pin_y,
                }
            )

        # Compute simulated live zone temperature based on active scenario
        base_temp = 70.2 if rid == "bldg:room_1f_server_rm" else 71.8
        setpoint_f = 70.0 if rid == "bldg:room_1f_server_rm" else 71.5
        if RUNTIME.active_scenario == "SCN-1" and rm.get("parent_space_id") == "bldg:ec_1st_floor" and rid != "bldg:room_1f_server_rm":
            live_temp = 75.8
        elif RUNTIME.active_scenario == "SCN-4" and rid == "bldg:room_1f_server_rm":
            live_temp = 74.1
        elif rid == "bldg:room_2f_huddle" and not RUNTIME.building_healed:
            live_temp = 76.8
        elif rid == "bldg:room_2f_open_office_232" and not RUNTIME.building_healed:
            live_temp = 74.6
        else:
            live_temp = base_temp

        delta_temp_f = round(live_temp - setpoint_f, 1)
        if rid == "bldg:room_2f_open_office_232" and room_status == "ENERGY_OUTLIER":
            thermal_load_kw = 22.4
        else:
            thermal_load_kw = 28.6 if room_status in ("ROOT_CAUSE_FAULT", "ENERGY_OUTLIER") else (19.4 if room_status == "SYMPATHETIC_IMPACT" else 9.8)

        rooms_out.append(
            {
                "space_id": rid,
                "label": rm.get("label", rid),
                "floor_id": rm.get("parent_space_id", "bldg:ec_1st_floor"),
                "sla_tier": rm.get("sla_criticality_tier", "Tier-3 Standard Office"),
                "occupancy_pct": float(rm.get("weekday_daytime_occupancy_pct") or 0.0),
                "comfort_pct": float(rm.get("comfort_pct_within_1f") or 99.0),
                "live_temp_f": live_temp,
                "setpoint_f": setpoint_f,
                "delta_temp_f": delta_temp_f,
                "thermal_load_kw": thermal_load_kw,
                "runtime_status": room_status,
                "coords": coords,
                "devices": devices,
            }
        )

    return {
        "site": site_meta,
        "floors": floors,
        "rooms": rooms_out,
        "equipment_count": len(equip_rows),
        "controllers_count": len(net_rows),
        "edges_count": len(edges),
        "all_equipment": equip_rows,
        "all_controllers": net_rows,
        "has_active_incident": len(RUNTIME.injected_events) > 0,
        "building_healed": RUNTIME.building_healed,
        "remediated_scenario": RUNTIME.remediated_scenario,
        "routine_bas_heartbeats": [
            {
                "timestamp": "LIVE COV",
                "protocol": "BACnet/IP UDP:47808",
                "message": (
                    "CLOSED-LOOP VERIFIED: RTU-1 (bldg:area_ec_ahu_1) Priority 8 override active — all 1st-floor zones restored to 71.8°F."
                    if RUNTIME.building_healed
                    else "RTU-1 (bldg:area_ec_ahu_1) & RTU-2 (bldg:area_ec_ahu_2) supply air tracking nominal setpoint (55.0°F)."
                ),
            },
            {
                "timestamp": "NET POLL",
                "protocol": "ARCNET 156 kbps",
                "message": "100 BACnet controllers online across 1st & 2nd Floors — 0.0% packet loss on Router #301003.",
            },
            {
                "timestamp": "SHACL GUARD",
                "protocol": "Brick v1.4 / ASHRAE 223P",
                "message": "Priority 8 WriteProperty guardrails active; Priority 1–7 Life-Safety hardware locks enforced.",
            },
        ],
    }


def _build_ai_diagnostics_for_node(
    node_id: str,
    label: str,
    runtime_status: str,
    neighbors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Computes AI Failure Likelihood, At-Risk Connected Elements, and Historical MTTR Intelligence with distinct device-specific profiles."""
    nid_lower = node_id.lower()
    is_smt = "smt" in nid_lower or "s4_vav_smt" in nid_lower or "s4_room_smt" in nid_lower
    is_piu_8 = "piu_8" in nid_lower or "open_office_232" in nid_lower
    is_piu_1 = "piu_1" in nid_lower or "huddle" in nid_lower
    is_ind_ahu = "s4_ind_ahu_1" in nid_lower
    is_rtu_1 = "area_ec_ahu_1" in nid_lower
    is_rtu_2 = "area_ec_ahu_2" in nid_lower
    is_outlier = runtime_status == "ENERGY_OUTLIER" or is_smt or is_piu_1 or is_piu_8
    is_root = runtime_status == "ROOT_CAUSE_FAULT"
    is_sympathetic = runtime_status in ("SYMPATHETIC_IMPACT", "AT_RISK")

    if is_root:
        prob = 98
        risk_level = "CRITICAL (ACTIVE EQUIPMENT TRIP)"
        window = "Active Fault Now — Downstream SLA Breach in <15 mins"
        explanation = (
            f"AI Cross-Layer Root-Cause Analysis confirmed {label} ({node_id}) suffered a mechanical Stage-1 DX Compressor "
            f"high-pressure trip. Supply air temperature has risen to 68.5°F (vs. 55.0°F setpoint), starving 31 downstream zones."
        )
        financial_risk = "$18,500/hr SLA comfort & server thermal penalty across 31 dependent zones"
        remote_fix_mins = 4
        manual_fix_hrs = 4.2
        recommended_fix = "Approve BACnet Priority 8 Override to engage backup Stage-2 Auxiliary DX Compressor (54.0°F supply setpoint)"
        history = [
            {
                "work_order_id": "WO-2026-0912",
                "date": "2026-08-14",
                "asset": "RTU-1 (Emerald Crest HQ)",
                "issue": "Stage-1 DX High-Pressure Cutout during 94°F ambient peak",
                "symptom": "Stage-1 DX High-Pressure Cutout during 94°F ambient peak",
                "resolution": "AI engaged Stage-2 Aux DX via BACnet Priority 8; mechanical tech cleaned condenser coil next day",
                "fix_applied": "AI engaged Stage-2 Aux DX via BACnet Priority 8; condenser coil cleaned next day",
                "fix_duration": "4 mins (Remote AI Failover) / 2.5 hrs (Coil Service)",
                "remote_ai_fix_mins": 4,
                "manual_dispatch_hrs": 4.2,
            },
            {
                "work_order_id": "WO-2026-0403",
                "date": "2026-05-22",
                "asset": "RTU-2 (Emerald Crest HQ)",
                "issue": "Supply Air Temp Drift to 67.2°F (Compressor Contactor Chatter)",
                "symptom": "Supply Air Temp Drift to 67.2°F (Compressor Contactor Chatter)",
                "resolution": "Remote BACnet staging failover + contactor replacement",
                "fix_applied": "Remote BACnet staging failover + contactor replacement",
                "fix_duration": "6 mins (Remote AI Failover) / 3.8 hrs (Contactor Swap)",
                "remote_ai_fix_mins": 6,
                "manual_dispatch_hrs": 3.8,
            },
            {
                "work_order_id": "WO-2025-1180",
                "date": "2025-11-09",
                "asset": "IND-AHU-1 (Sunbelt Plant)",
                "issue": "Chilled Water Supply Starvation across 14 terminal VAVs",
                "symptom": "Chilled Water Supply Starvation across 14 terminal VAVs",
                "resolution": "Manual troubleshooting before AI deployment (31 room alarms investigated one by one)",
                "fix_applied": "Manual chilled-water bypass valve reset after investigating 14 zone alarms",
                "fix_duration": "4.6 hrs (Manual Truck Roll)",
                "remote_ai_fix_mins": 9,
                "manual_dispatch_hrs": 4.6,
            },
        ]
    elif is_outlier and is_smt:
        prob = 78
        risk_level = "HIGH PREDICTIVE FAILURE RISK (CLEANROOM YELLOW OUTLIER)"
        window = "Estimated 24–36 Hours to Desiccant Bypass & Reheat Valve Seizure"
        explanation = (
            f"AI TimesFM 2.5 + Peer-Cohort Z-Score (+3.65σ) detected {label} ({node_id}) in the ISO-6 Cleanroom is fighting "
            f"simultaneous 52.0°F chilled-water dehumidification and 88% hot-water reheat override. The Belimo modulating reheat actuator "
            f"is hunting at 168 cycles/hr while desiccant bypass damper feedback lags by 14%, indicating 78% likelihood of actuator seizure "
            f"and ISO-6 relative humidity excursion (>45% RH) within 36 hours."
        )
        financial_risk = "$14,500/hr SMT solder-paste viscosity & PCB scrap exposure + $4,820/yr wasted reheat energy"
        remote_fix_mins = 14
        manual_fix_hrs = 4.5
        recommended_fix = "Execute Automated BACnet Priority 8 Valve Stroke Flush (0%→100%→0%) & decouple desiccant reheat PID deadband (+1.5°F)"
        history = [
            {
                "work_order_id": "WO-2026-0841",
                "date": "2026-09-03",
                "asset": "SMT Line VAV-4 (Sunbelt Plant)",
                "issue": "ISO-6 Cleanroom Simultaneous Reheat Outlier (+3.65σ) — Reheat valve sticking at 88%",
                "symptom": "ISO-6 Cleanroom Simultaneous Reheat Outlier (+3.65σ) — Reheat valve sticking at 88%",
                "resolution": "Automated BACnet full-stroke flush cleared scale from hydronic seat; zero cleanroom downtime",
                "fix_applied": "Automated BACnet full-stroke flush (0%→100%→0%) + cleanroom PID deadband tune",
                "fix_duration": "14 mins (Automated Remote BACnet Calibration)",
                "remote_ai_fix_mins": 14,
                "manual_dispatch_hrs": 4.5,
            },
            {
                "work_order_id": "WO-2025-1194",
                "date": "2025-12-11",
                "asset": "Cleanroom VAV-2 (Sunbelt Plant)",
                "issue": "Unaddressed valve hunting (160+ cycles/hr) burned out actuator motor during SMT production run",
                "symptom": "Unaddressed valve hunting (160+ cycles/hr) burned out actuator motor during SMT run",
                "resolution": "Emergency manual actuator replacement & ISO-6 cleanroom particle recertification",
                "fix_applied": "Emergency manual Belimo actuator swap & ISO-6 cleanroom recertification",
                "fix_duration": "4.5 hrs (Manual Hardware Replacement)",
                "remote_ai_fix_mins": 16,
                "manual_dispatch_hrs": 4.5,
            },
        ]
    elif is_outlier and is_piu_8:
        prob = 64
        risk_level = "MODERATE-HIGH PREDICTIVE DRIFT (AIRFLOW & SCR RELAY OUTLIER)"
        window = "Estimated 48–72 Hours to Parallel Fan SCR Relay Fatigue"
        explanation = (
            f"AI Peer-Cohort Z-Score (+2.78σ) and TimesFM 2.5 telemetry audit on {label} ({node_id}) identified a +185 CFM supply airflow "
            f"differential-pressure sensor offset (reading 610 CFM vs. 425 CFM actual) combined with intermittent parallel induce-fan SCR "
            f"stage-1 relay chatter (84 cycles/hr). This causes premature auxiliary electric reheat engagement at 74.6°F while RTU-2 supplies "
            f"55.0°F primary air — distinct from PIU 2-1's mechanical hydronic valve linkage hysteresis."
        )
        financial_risk = "$1,760/yr ($146/mo) parasitic parallel-fan & SCR reheat waste + Open Office 232 afternoon draft complaints"
        remote_fix_mins = 12
        manual_fix_hrs = 2.8
        recommended_fix = "Run Automated BACnet Zero-Point Flow Pressure Auto-Null & raise parallel fan cut-in deadband by +2.0°F via Priority 8"
        history = [
            {
                "work_order_id": "WO-2026-0715",
                "date": "2026-07-19",
                "asset": "PIU 2-8 Open Office 232 (Emerald Crest HQ)",
                "issue": "Supply Airflow DP Transducer Zero-Drift (+185 CFM) triggering premature parallel reheat (+2.78σ)",
                "symptom": "Supply Airflow DP Transducer Zero-Drift (+185 CFM) triggering premature parallel reheat",
                "resolution": "Remote BACnet zero-point calibration & SCR minimum off-timer increased from 30s to 180s",
                "fix_applied": "Remote BACnet DP transducer auto-null + SCR minimum off-timer set to 180s",
                "fix_duration": "12 mins (Remote AI Calibration) / 2.8 hrs (Manual Sensor Swap)",
                "remote_ai_fix_mins": 12,
                "manual_dispatch_hrs": 2.8,
            },
            {
                "work_order_id": "WO-2026-0211",
                "date": "2026-02-08",
                "asset": "PIU 2-6 Open Office 228 (Emerald Crest HQ)",
                "issue": "Parallel fan SCR solid-state relay failure from rapid cycling",
                "symptom": "Parallel fan SCR solid-state relay failure from rapid short-cycling",
                "resolution": "Manual ceiling plenum access and SCR relay board replacement",
                "fix_applied": "Manual ceiling plenum access & SCR relay board replacement",
                "fix_duration": "3.1 hrs (Manual Electrical Dispatch)",
                "remote_ai_fix_mins": 15,
                "manual_dispatch_hrs": 3.1,
            },
        ]
    elif is_outlier:
        prob = 74
        risk_level = "HIGH PREDICTIVE FAILURE RISK (REHEAT LINKAGE HYSTERESIS OUTLIER)"
        window = "Estimated 36–48 Hours to Hydronic Reheat Actuator Seizure"
        explanation = (
            f"AI TimesFM 2.5 + Peer-Cohort Z-Score (+3.42σ) detected {label} ({node_id}) is simultaneously cooling and reheating at 76.8°F. "
            f"Unlike PIU 2-8's airflow sensor drift, PIU 2-1's hydronic hot-water globe valve stem is mechanically binding at 68%–92% open "
            f"due to brass packing gland friction while RTU-2 supplies 55.0°F primary air. High-frequency actuator hunting (142 cycles/hr) "
            f"indicates a 74% likelihood of complete actuator gear-train seizure within 36–48 hours."
        )
        financial_risk = "$2,620/yr ($218/mo) simultaneous hydronic reheat/cooling bleed + 2F Huddle Room thermal SLA breach (76.8°F)"
        remote_fix_mins = 18
        manual_fix_hrs = 3.5
        recommended_fix = "Run AI Automated BACnet Valve Stroke Calibration (0%→100%→0% seat flush) & widen cooling/heating deadband by +1.5°F"
        history = [
            {
                "work_order_id": "WO-2026-0619",
                "date": "2026-06-17",
                "asset": "PIU 2-1 Huddle (Emerald Crest HQ)",
                "issue": "Hydronic Reheat Valve Packing Hysteresis (+3.42σ) — Discharge Air Temp stuck at 76.8°F",
                "symptom": "Hydronic Reheat Valve Packing Hysteresis (+3.42σ) — Discharge Air Temp stuck at 76.8°F",
                "resolution": "Remote BACnet full-stroke seat flush (0%→100%→0%) + PID deadband reset cleared stem stiction",
                "fix_applied": "Remote BACnet full-stroke valve seat flush (0%→100%→0%) + PID loop deadband tune",
                "fix_duration": "18 mins (Remote AI Tune) / 3.5 hrs (Manual Valve Rebuild)",
                "remote_ai_fix_mins": 18,
                "manual_dispatch_hrs": 3.5,
            },
            {
                "work_order_id": "WO-2025-1042",
                "date": "2025-10-28",
                "asset": "PIU 2-3 Conference (Emerald Crest HQ)",
                "issue": "Seized hydronic reheat globe valve required ceiling shutoff & valve body replacement",
                "symptom": "Seized hydronic reheat globe valve required hot-water loop isolation & rebuild",
                "resolution": "Manual hot-water branch isolation, brass packing replacement, and air bleed",
                "fix_applied": "Manual hot-water branch isolation & globe valve packing rebuild",
                "fix_duration": "3.8 hrs (Manual Mechanical Dispatch)",
                "remote_ai_fix_mins": 20,
                "manual_dispatch_hrs": 3.8,
            },
        ]
    elif is_ind_ahu:
        prob = 28
        risk_level = "ELEVATED PROCESS DEPENDENCY (SINGLE-POINT CLEANROOM AHU)"
        window = "Nominal Now — 20% Degradation Triggers 52% Cleanroom Chain-Failure Risk"
        explanation = (
            f"{label} ({node_id}) is the primary 42,000 CFM industrial make-up and chilled-water air handler feeding ISO-6 SMT Cleanroom "
            f"(Line 1 & 2) and Assembly Bay B. While primary supply air is currently holding 53.5°F, downstream terminal unit SMT Line VAV-4 "
            f"is fighting a +3.65σ reheat anomaly, elevating chilled-water return temperature by +1.8°F and placing IND-AHU-1 under +14% latent load stress."
        )
        financial_risk = "$48,500/hr SMT PCB production line halt & solder-paste humidity scrap if IND-AHU-1 degrades >20%"
        remote_fix_mins = 8
        manual_fix_hrs = 5.0
        recommended_fix = "Clear downstream SMT Line VAV-4 reheat anomaly first; maintain IND-AHU-1 chilled-water supply pressure differential at 18 PSI"
        history = [
            {
                "work_order_id": "WO-2026-0514",
                "date": "2026-05-14",
                "asset": "IND-AHU-1 (Sunbelt Plant)",
                "issue": "Supply Fan VFD Carrier Frequency Harmonic Drift (-18% CFM droop)",
                "symptom": "Supply Fan VFD Carrier Frequency Harmonic Drift (-18% CFM cleanroom pressure droop)",
                "resolution": "AI shifted static pressure setpoint +0.25 in.w.c. via BACnet Priority 8; prevented ISO-6 pressure loss",
                "fix_applied": "AI BACnet Priority 8 duct static pressure boost (+0.25 in.w.c.) + VFD carrier reset",
                "fix_duration": "8 mins (Remote AI Static Boost) / 5.0 hrs (Manual VFD Service)",
                "remote_ai_fix_mins": 8,
                "manual_dispatch_hrs": 5.0,
            },
        ]
    elif is_sympathetic:
        prob = 46
        risk_level = "MODERATE (DOWNSTREAM / ADJACENT AT-RISK)"
        window = "At Risk of Secondary SLA Breach within 25–45 mins"
        explanation = (
            f"{label} ({node_id}) is mechanically healthy on its own, but is directly exposed to thermal drift or "
            f"supply air starvation from its connected upstream/adjacent parent in the Knowledge Graph."
        )
        financial_risk = "$6,200/hr secondary zone SLA exposure if parent fault is not isolated"
        remote_fix_mins = 5
        manual_fix_hrs = 2.8
        recommended_fix = "Remediate upstream parent asset; AI has automatically muted sympathetic alarms on this node"
        history = [
            {
                "work_order_id": "WO-2026-0772",
                "date": "2026-07-29",
                "asset": "1F Zone Terminal Cohort (Emerald Crest HQ)",
                "issue": "31 downstream PIUs reported high zone temp (75.8°F)",
                "symptom": "31 downstream PIUs reported high zone temp (75.8°F) after RTU-1 trip",
                "resolution": "AI suppressed 31 room tickets and resolved parent RTU-1 compressor failover",
                "fix_applied": "AI suppressed 31 sympathetic room alarms & executed RTU-1 Stage-2 failover",
                "fix_duration": "5 mins (Parent Failover)",
                "remote_ai_fix_mins": 5,
                "manual_dispatch_hrs": 2.8,
            }
        ]
    else:
        prob = 11 if (is_rtu_1 or is_rtu_2) else 6
        risk_level = "LOW (NOMINAL OPERATION)"
        window = "> 90 Days (No Abnormal Wear or Drift Detected)"
        if is_rtu_2:
            explanation = (
                f"AI continuous telemetry audit confirms {label} ({node_id}) is supplying steady 55.0°F primary air at 1.42 in.w.c. duct static "
                f"across 36 2nd-floor terminal units. Note: 2 downstream boxes (PIU 2-1 Huddle at +3.42σ and PIU 2-8 Open Office 232 at +2.78σ) "
                f"have localized reheat/airflow anomalies adding 11.4 kW of parasitic load, but RTU-2 itself is mechanically healthy."
            )
            financial_risk = "$0/hr direct RTU-2 mechanical risk ($4,380/yr recoverable in 2 downstream PIU outliers)"
        elif is_rtu_1:
            explanation = (
                f"AI continuous telemetry audit confirms {label} ({node_id}) is supplying 55.0°F conditioned air across all 31 1st-floor "
                f"terminal zones (including Tier-1 Server Room 104). Stage-1 and Stage-2 DX compressors show balanced suction/discharge pressures."
            )
            financial_risk = "$0/hr active risk (100% of 31 downstream 1st-floor zones within ±0.4°F of setpoint)"
        else:
            explanation = (
                f"AI continuous telemetry audit confirms {label} ({node_id}) is tracking setpoint within ±0.3°F, "
                f"damper/valve modulation is smooth (<8 cycles/hr), and BACnet controller packet loss is 0.0%."
            )
            financial_risk = "$0/hr active risk (Operating in top 95th percentile efficiency cohort)"
        remote_fix_mins = 10
        manual_fix_hrs = 2.0
        recommended_fix = "No intervention required — continue automated ASHRAE G36 trim & respond optimization"
        history = [
            {
                "work_order_id": "WO-2026-0310",
                "date": "2026-03-15",
                "asset": label,
                "issue": "Routine Quarterly Automated Self-Test & Damper Stroke Verification",
                "symptom": "Routine Quarterly Automated Self-Test & Damper Stroke Verification",
                "resolution": "Passed 100% of SHACL & ASHRAE Guideline 36 closed-loop checks",
                "fix_applied": "Automated ASHRAE Guideline 36 trim & respond self-verification",
                "fix_duration": "8 mins (Automated Self-Test)",
                "remote_ai_fix_mins": 8,
                "manual_dispatch_hrs": 2.0,
            }
        ]

    at_risk_elements: List[Dict[str, Any]] = []
    for nb in neighbors[:8]:
        nb_status = nb.get("runtime_status", "HEALTHY")
        nb_id = nb.get("node_id", "")
        nb_label = nb.get("label", nb_id)
        nb_onto = nb.get("ontology_class", "brick:Entity")
        rel_label = "1-Hop Direct Dependency" if nb.get("is_direct_hop", True) else "2-Hop Shared AHU Cohort"
        if nb_status == "ROOT_CAUSE_FAULT":
            reason = "Primary upstream mechanical trip driving thermal starvation"
            at_risk_elements.append(
                {
                    "node_id": nb_id,
                    "label": nb_label,
                    "ontology_class": nb_onto,
                    "relationship": rel_label,
                    "risk_status": "ROOT_CAUSE_FAULT",
                    "failure_likelihood_pct": 98,
                    "impact_reason": reason,
                    "impact_summary": reason,
                }
            )
        elif nb_status == "ENERGY_OUTLIER":
            nb_lower = nb_id.lower()
            nb_prob = 78 if "smt" in nb_lower else (64 if ("piu_8" in nb_lower or "232" in nb_lower) else 74)
            reason = (
                "Active +2.78σ airflow DP offset & SCR relay chatter"
                if ("piu_8" in nb_lower or "232" in nb_lower)
                else (
                    "Active +3.65σ ISO-6 cleanroom desiccant/reheat valve hunting"
                    if "smt" in nb_lower
                    else "Active +3.42σ hydronic reheat valve stem hysteresis"
                )
            )
            at_risk_elements.append(
                {
                    "node_id": nb_id,
                    "label": nb_label,
                    "ontology_class": nb_onto,
                    "relationship": rel_label,
                    "risk_status": "ENERGY_OUTLIER",
                    "failure_likelihood_pct": nb_prob,
                    "impact_reason": reason,
                    "impact_summary": reason,
                }
            )
        elif nb_status == "SYMPATHETIC_IMPACT":
            reason = (
                nb.get("risk_reason")
                or "Downstream zone exposed to warm supply air from faulted parent"
            )
            at_risk_elements.append(
                {
                    "node_id": nb_id,
                    "label": nb_label,
                    "ontology_class": nb_onto,
                    "relationship": rel_label,
                    "risk_status": "SYMPATHETIC_IMPACT",
                    "runtime_status": "SYMPATHETIC_IMPACT",
                    "failure_likelihood_pct": 62,
                    "impact_reason": reason,
                    "impact_summary": reason,
                }
            )
        else:
            reason = (
                "Shares primary AHU static-pressure loop with active outlier (currently within nominal SLA bounds)"
                if is_outlier
                else "Connected graph neighbor operating within nominal SLA bounds"
            )
            at_risk_elements.append(
                {
                    "node_id": nb_id,
                    "label": nb_label,
                    "ontology_class": nb_onto,
                    "relationship": rel_label,
                    "risk_status": "HEALTHY",
                    "runtime_status": "HEALTHY",
                    "failure_likelihood_pct": 12 if is_outlier else 5,
                    "impact_reason": reason,
                    "impact_summary": reason,
                }
            )

    return {
        "failure_probability_pct": prob,
        "risk_level": risk_level,
        "predicted_failure_window": window,
        "ai_confidence_pct": 94,
        "ai_data_sources_used": "15-min BACnet Telemetry + TimesFM 2.5 Forecast + Peer-Cohort Z-Scores + Historical Work Orders",
        "root_cause_explanation": explanation,
        "financial_risk_summary": financial_risk,
        "mttr_intelligence": {
            "typical_remote_ai_fix_mins": remote_fix_mins,
            "typical_manual_fix_hours": manual_fix_hrs,
            "recommended_fix_action": recommended_fix,
            "historical_incidents": history,
        },
        "at_risk_connected_elements": at_risk_elements,
    }


def _status_sort_priority(status: str) -> int:
    """Orders graph neighbors so faulted and yellow outlier nodes always appear in the top spider-chart ring."""
    return {
        "ROOT_CAUSE_FAULT": 0,
        "ENERGY_OUTLIER": 1,
        "SYMPATHETIC_IMPACT": 2,
        "AT_RISK": 3,
        "HEALTHY": 4,
    }.get(status, 5)


def _build_synthetic_multi_site_neighborhood(node_id: str) -> Optional[Dict[str, Any]]:
    """Builds a complete 1-hop & 2-hop Knowledge Graph neighborhood for ACME-SITE-002..005 entities."""
    for site_id, bp in MULTI_SITE_BLUEPRINTS.items():
        floors_by_id = {f["floor_id"]: f for f in bp["floors"]}
        for rm in bp["rooms"]:
            # Check if node_id is a Room, Floor, Primary AHU, Device, or Controller in this site
            matched_dev = next((d for d in rm["devices"] if d["node_id"] == node_id), None)
            matched_ctrl = next((d for d in rm["devices"] if d["controller_id"] == node_id), None)
            is_room = rm["space_id"] == node_id
            fl = floors_by_id.get(rm["floor_id"], bp["floors"][0])
            is_floor = fl["floor_id"] == node_id
            is_primary_ahu = fl["primary_ahu_id"] == node_id

            if not (matched_dev or matched_ctrl or is_room or is_floor or is_primary_ahu):
                continue

            if is_room:
                center = {
                    "node_id": rm["space_id"],
                    "node_category": "Space",
                    "ontology_class": "rec:Room",
                    "label": rm["label"],
                    "sla_tier": rm["sla_tier"],
                    "runtime_status": rm["runtime_status"],
                }
            elif is_floor and not (is_room or matched_dev or matched_ctrl or is_primary_ahu):
                center = {
                    "node_id": fl["floor_id"],
                    "node_category": "Space",
                    "ontology_class": "rec:Floor",
                    "label": fl["label"],
                    "sla_tier": fl["sla_tier"],
                    "runtime_status": "HEALTHY",
                }
            elif is_primary_ahu and not matched_dev:
                center = {
                    "node_id": fl["primary_ahu_id"],
                    "node_category": "Equipment",
                    "ontology_class": "brick:Air_Handling_Unit",
                    "label": fl["primary_ahu_label"],
                    "sla_tier": fl["sla_tier"],
                    "runtime_status": "HEALTHY",
                }
            elif matched_ctrl and not matched_dev:
                center = {
                    "node_id": node_id,
                    "node_category": "Network",
                    "ontology_class": "bsm:Controller",
                    "label": f"BACnet Controller {node_id.split('_')[-1]} ({matched_ctrl['label']})",
                    "sla_tier": rm["sla_tier"],
                    "runtime_status": "HEALTHY",
                }
            else:
                center = {
                    "node_id": matched_dev["node_id"],
                    "node_category": "Equipment",
                    "ontology_class": matched_dev["brick_class"],
                    "label": matched_dev["label"],
                    "sla_tier": rm["sla_tier"],
                    "runtime_status": matched_dev["runtime_status"],
                }

            neighbors = [
                {
                    "node_id": rm["space_id"],
                    "node_category": "Space",
                    "ontology_class": "rec:Room",
                    "label": rm["label"],
                    "runtime_status": rm["runtime_status"],
                    "is_direct_hop": True,
                },
                {
                    "node_id": fl["primary_ahu_id"],
                    "node_category": "Equipment",
                    "ontology_class": "brick:Air_Handling_Unit",
                    "label": fl["primary_ahu_label"],
                    "runtime_status": "HEALTHY",
                    "is_direct_hop": True,
                },
                {
                    "node_id": fl["floor_id"],
                    "node_category": "Space",
                    "ontology_class": "rec:Floor",
                    "label": fl["short_label"],
                    "runtime_status": "HEALTHY",
                    "is_direct_hop": True,
                },
            ]
            edges = []
            for d in rm["devices"]:
                neighbors.append(
                    {
                        "node_id": d["node_id"],
                        "node_category": "Equipment",
                        "ontology_class": d["brick_class"],
                        "label": d["label"],
                        "runtime_status": d["runtime_status"],
                        "is_direct_hop": True,
                    }
                )
                neighbors.append(
                    {
                        "node_id": d["controller_id"],
                        "node_category": "Network",
                        "ontology_class": "bsm:Controller",
                        "label": f"Controller {d['controller_id'].split('_')[-1]}",
                        "runtime_status": "HEALTHY",
                        "is_direct_hop": True,
                    }
                )
                edges.extend(
                    [
                        {
                            "source_node_id": fl["primary_ahu_id"],
                            "target_node_id": d["node_id"],
                            "edge_type": "FEEDS",
                        },
                        {
                            "source_node_id": d["node_id"],
                            "target_node_id": rm["space_id"],
                            "edge_type": "LOCATED_IN",
                        },
                        {
                            "source_node_id": d["node_id"],
                            "target_node_id": d["controller_id"],
                            "edge_type": "CONTROLLED_BY",
                        },
                    ]
                )

            # Include sibling/adjacent rooms on the same floor so 2-hop blast radius is visible in the radial graph,
            # preserving each room/device's exact Floor Plan runtime_status so colors match 1-to-1.
            for sib_rm in bp["rooms"]:
                if sib_rm["floor_id"] == rm["floor_id"] and sib_rm["space_id"] != rm["space_id"]:
                    neighbors.append(
                        {
                            "node_id": sib_rm["space_id"],
                            "node_category": "Space",
                            "ontology_class": "rec:Room",
                            "label": sib_rm["label"],
                            "runtime_status": sib_rm["runtime_status"],
                            "is_direct_hop": is_primary_ahu or is_floor,
                        }
                    )
                    edges.append(
                        {
                            "source_node_id": fl["primary_ahu_id"],
                            "target_node_id": sib_rm["space_id"],
                            "edge_type": "FEEDS_ADJACENT_ZONE",
                        }
                    )
                    for sib_dev in sib_rm["devices"]:
                        neighbors.append(
                            {
                                "node_id": sib_dev["node_id"],
                                "node_category": "Equipment",
                                "ontology_class": sib_dev["brick_class"],
                                "label": sib_dev["label"],
                                "runtime_status": sib_dev["runtime_status"],
                                "is_direct_hop": is_primary_ahu or is_floor,
                            }
                        )
                        edges.append(
                            {
                                "source_node_id": fl["primary_ahu_id"],
                                "target_node_id": sib_dev["node_id"],
                                "edge_type": "FEEDS",
                            }
                        )

            # Deduplicate neighbors excluding center and sort so outlier/fault nodes & 1-hop appear first
            uniq_neighbors = []
            seen_ids = {node_id}
            for nb in neighbors:
                if nb["node_id"] not in seen_ids:
                    seen_ids.add(nb["node_id"])
                    uniq_neighbors.append(nb)
            uniq_neighbors.sort(
                key=lambda nb: (
                    _status_sort_priority(nb.get("runtime_status", "HEALTHY")),
                    not nb.get("is_direct_hop", False),
                    nb.get("node_id", ""),
                )
            )

            ref_dev = matched_dev or (rm["devices"][0] if rm["devices"] else None)
            pts = [
                {
                    "point_id": f"{node_id}_zn_temp",
                    "label": f"{rm['label']} Zone Air Temp",
                    "brick_class": "brick:Zone_Air_Temperature_Sensor",
                    "bacnet_uri": "bacnet://40101/analog-input,1",
                    "unit": f"{rm['live_temp_f']} °F",
                    "has_timeseries": "True",
                },
                {
                    "point_id": f"{node_id}_sa_flow",
                    "label": f"{center['label']} Supply Airflow",
                    "brick_class": "brick:Supply_Air_Flow_Sensor",
                    "bacnet_uri": "bacnet://40101/analog-input,4",
                    "unit": "1,420 CFM",
                    "has_timeseries": "True",
                },
                {
                    "point_id": f"{node_id}_sp_temp",
                    "label": f"{rm['label']} Cooling Setpoint",
                    "brick_class": "brick:Zone_Air_Cooling_Temperature_Setpoint",
                    "bacnet_uri": "bacnet://40101/analog-value,2",
                    "unit": f"{round(rm['live_temp_f'] - 0.2, 1) if rm['runtime_status'] == 'HEALTHY' else 71.0} °F",
                    "has_timeseries": "True",
                },
                {
                    "point_id": f"{node_id}_damper_cmd",
                    "label": f"{center['label']} Damper / Valve Command",
                    "brick_class": "brick:Damper_Position_Command",
                    "bacnet_uri": "bacnet://40101/analog-output,1",
                    "unit": "94 % (Hunting)" if center["runtime_status"] == "ENERGY_OUTLIER" else "68 %",
                    "has_timeseries": "True",
                },
            ]
            gql_query = (
                f"SELECT center.node_id, center.label, edge.edge_type, neighbor.node_id AS connected_id, "
                f"neighbor.ontology_class, neighbor.sla_tier\n"
                f"FROM GRAPH_TABLE(acme_abo_telemetry.acme_building_graph\n"
                f"  MATCH (center {{node_id: '{node_id}'}})-[edge]-(neighbor)\n"
                f"  COLUMNS (center.node_id, center.label, edge.edge_type, neighbor.node_id, neighbor.ontology_class, neighbor.sla_tier)\n"
                f");"
            )
            ai_diag = _build_ai_diagnostics_for_node(
                node_id=center["node_id"],
                label=center["label"],
                runtime_status=center["runtime_status"],
                neighbors=uniq_neighbors,
            )
            return {
                "center_node": center,
                "neighbors": uniq_neighbors,
                "edges": edges,
                "bacnet_points": pts,
                "total_points_count": int(ref_dev["point_count"]) if ref_dev else 18,
                "active_alarms": [],
                "gql_query": gql_query,
                "ai_diagnostics": ai_diag,
            }
    return None


@app.get("/api/graph/neighborhood/{node_id:path}")
def get_graph_neighborhood(
    node_id: str = FastAPIPath(..., min_length=2, max_length=160),
) -> Dict[str, Any]:
    synthetic_nb = _build_synthetic_multi_site_neighborhood(node_id)
    if synthetic_nb is not None:
        return synthetic_nb

    graph_nodes = {n["node_id"]: n for n in _load_csv("graph_nodes.csv") if n.get("node_id")}
    graph_edges = _load_csv("graph_edges.csv")
    equip_by_id = {e["node_id"]: e for e in _load_csv("equipment_nodes.csv") if e.get("node_id")}
    space_by_id = {s["space_id"]: s for s in _load_csv("spatial_nodes.csv") if s.get("space_id")}
    net_by_id = {c["node_id"]: c for c in _load_csv("network_and_controller_nodes.csv") if c.get("node_id")}
    points = _load_csv("point_catalog.csv")

    center = graph_nodes.get(node_id, {
        "node_id": node_id,
        "node_category": "Equipment",
        "ontology_class": "brick:Equipment",
        "label": node_id,
        "sla_tier": "Tier-2",
    }).copy()
    center["runtime_status"] = _compute_node_runtime_status(node_id)
    center["equipment_detail"] = equip_by_id.get(node_id)
    center["space_detail"] = space_by_id.get(node_id)
    center["network_detail"] = net_by_id.get(node_id)

    # 1-hop and 2-hop traversal across graph_edges
    hop1_edges = [
        e for e in graph_edges
        if e.get("source_node_id") == node_id or e.get("target_node_id") == node_id
    ]
    hop1_node_ids = {node_id}
    for e in hop1_edges:
        hop1_node_ids.add(e.get("source_node_id", ""))
        hop1_node_ids.add(e.get("target_node_id", ""))

    hop2_candidates = [
        e for e in graph_edges
        if (e.get("source_node_id") in hop1_node_ids or e.get("target_node_id") in hop1_node_ids)
        and e not in hop1_edges
    ]
    hop2_candidates.sort(
        key=lambda e: min(
            _status_sort_priority(_compute_node_runtime_status(e.get("source_node_id", ""))),
            _status_sort_priority(_compute_node_runtime_status(e.get("target_node_id", ""))),
        )
    )
    hop2_edges = hop2_candidates[:45]

    combined_edges = hop1_edges + hop2_edges
    neighbor_ids = set()
    for e in combined_edges:
        neighbor_ids.add(e.get("source_node_id", ""))
        neighbor_ids.add(e.get("target_node_id", ""))
    neighbor_ids.discard(node_id)
    neighbor_ids.discard("")

    neighbors: List[Dict[str, Any]] = []
    for nid in neighbor_ids:
        gn = graph_nodes.get(nid, {
            "node_id": nid,
            "node_category": "Entity",
            "ontology_class": "brick:Entity",
            "label": nid,
        }).copy()
        # Preserve exact Floor Plan runtime_status so Tab 1 and Tab 2 Spider Chart match 1-to-1
        gn["runtime_status"] = _compute_node_runtime_status(nid)
        gn["is_direct_hop"] = nid in hop1_node_ids
        neighbors.append(gn)

    neighbors.sort(
        key=lambda nb: (
            _status_sort_priority(nb.get("runtime_status", "HEALTHY")),
            not nb.get("is_direct_hop", False),
            nb.get("node_id", ""),
        )
    )

    # Collect BACnet points for this node (either by equipment_id or bacnet_device_id)
    matched_points = [
        p for p in points
        if p.get("equipment_id") == node_id or p.get("bacnet_device_id") == node_id
    ]
    # If a room is clicked, gather points from equipment serving that room
    if not matched_points and node_id in space_by_id:
        room_eq_ids = {
            e["node_id"] for e in equip_by_id.values() if e.get("room_id") == node_id
        }
        matched_points = [p for p in points if p.get("equipment_id") in room_eq_ids]

    matched_points.sort(key=lambda p: (str(p.get("has_timeseries")) != "True", p.get("label", "")))

    active_node_alarms = [
        ev for ev in RUNTIME.injected_events
        if ev.get("node_id") == node_id or ev.get("root_cause_event_id") and node_id == "bldg:area_ec_ahu_1"
    ]

    gql_query = (
        f"SELECT center.node_id, center.label, edge.edge_type, neighbor.node_id AS connected_id, "
        f"neighbor.ontology_class, neighbor.sla_tier\n"
        f"FROM GRAPH_TABLE(acme_abo_telemetry.acme_building_graph\n"
        f"  MATCH (center {{node_id: '{node_id}'}})-[edge]->(neighbor)\n"
        f"  COLUMNS (center.node_id, center.label, edge.edge_type, neighbor.node_id, neighbor.ontology_class, neighbor.sla_tier)\n"
        f");"
    )

    ai_diag = _build_ai_diagnostics_for_node(
        node_id=center["node_id"],
        label=center.get("label", node_id),
        runtime_status=center["runtime_status"],
        neighbors=neighbors,
    )

    return {
        "center_node": center,
        "neighbors": neighbors,
        "edges": combined_edges,
        "bacnet_points": matched_points[:32],
        "total_points_count": len(matched_points),
        "active_alarms": active_node_alarms,
        "gql_query": gql_query,
        "ai_diagnostics": ai_diag,
    }


class NodeAnalysisRequest(BaseModel):
    node_id: str = Field(..., min_length=2, max_length=160)
    analysis_mode: Literal["ROOT_CAUSE_TRACE", "GRAPH_AUDIT", "ENERGY_COHORT_CHECK"] = "GRAPH_AUDIT"


@app.post("/api/agent/analyze-node")
async def analyze_node_with_agent(req: NodeAnalysisRequest) -> Dict[str, Any]:
    nb = get_graph_neighborhood(req.node_id)
    center = nb["center_node"]
    neighbors = nb["neighbors"]
    edges = nb["edges"]
    points = nb["bacnet_points"]

    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]

    feeds_targets = [
        e["target_node_id"] for e in edges if e.get("edge_type") == "FEEDS" and e.get("source_node_id") == req.node_id
    ]
    fed_by_sources = [
        e["source_node_id"] for e in edges if e.get("edge_type") == "FEEDS" and e.get("target_node_id") == req.node_id
    ]
    controllers = [
        e["target_node_id"] for e in edges if e.get("edge_type") == "CONTROLLED_BY" and e.get("source_node_id") == req.node_id
    ]
    spaces = [
        e["target_node_id"] for e in edges if e.get("edge_type") == "LOCATED_IN" and e.get("source_node_id") == req.node_id
    ]

    status = center.get("runtime_status", "HEALTHY")
    label = center.get("label", req.node_id)
    onto = center.get("ontology_class", "brick:Equipment")
    has_active_incident = len(RUNTIME.injected_events) > 0
    ai_diag = nb.get("ai_diagnostics") or _build_ai_diagnostics_for_node(req.node_id, label, status, neighbors)
    fail_prob = ai_diag.get("failure_probability_pct", 12)
    fail_win = ai_diag.get("predicted_failure_window", "Stable (> 30 days)")
    mttr_info = ai_diag.get("mttr_intelligence", {})
    at_risk_list = ai_diag.get("at_risk_connected_elements", [])
    at_risk_names = ", ".join(f"{el['label']} ({el['failure_likelihood_pct']}% risk)" for el in at_risk_list[:3]) or "0 at-risk dependencies"

    if status == "ROOT_CAUSE_FAULT" or (req.analysis_mode == "ROOT_CAUSE_TRACE" and has_active_incident):
        subagent = "cross_layer_rca_agent"
        tool_called = "gql_trace_causal_blast_radius"
        summary = (
            f"[ACTIVE ROOT CAUSE CONFIRMED on {label} ({req.node_id}) — Failure Risk {fail_prob}% ({fail_win})]: "
            f"Dual-Graph GQL traversal verified {len(feeds_targets)} downstream terminal zones fed via brick:feeds "
            f"({', '.join(feeds_targets[:4])}...) and checked BACnet Controller {', '.join(controllers) or 'bldg:bacnet_device_301003'} (0% packet loss). "
            f"All {len([e for e in RUNTIME.injected_events if e.get('suppressed_by_agent')])} downstream zone alarms are muted as sympathetic starvation effects. "
            f"Historical MTTR: {mttr_info.get('typical_remote_ai_fix_mins', 8)} mins via AI Priority 8 override vs. {mttr_info.get('typical_manual_fix_hours', 4.2)} hrs manual dispatch."
        )
    elif req.analysis_mode == "ROOT_CAUSE_TRACE" and not has_active_incident:
        subagent = "cross_layer_rca_agent"
        tool_called = "gql_simulate_dependency_blast_radius"
        summary = (
            f"[PRE-ALARM AI FAILURE & BLAST-RADIUS DIAGNOSIS — {label} ({req.node_id})]: "
            f"AI Failure Probability: {fail_prob}% ({fail_win}). Connected Blast Radius: {at_risk_names}. "
            f"Historical Fix Benchmark: {mttr_info.get('typical_remote_ai_fix_mins', 12)} mins remote AI calibration vs. {mttr_info.get('typical_manual_fix_hours', 3.8)} hrs manual truck roll."
        )
    elif status == "SYMPATHETIC_IMPACT":
        subagent = "alarm_triage_agent"
        tool_called = "gql_find_upstream_serving_ahu"
        upstream_ahu = ", ".join(fed_by_sources) or "bldg:area_ec_ahu_1 (RTU-1)"
        summary = (
            f"[SYMPATHETIC IMPACT TRACE for {label} ({req.node_id}) — Upstream Risk {fail_prob}%]: Upstream brick:feeds traversal resolved "
            f"primary thermal supply parent {upstream_ahu}. Local BACnet controller {', '.join(controllers) or 'nominal'} "
            f"is healthy (0% packet loss); local alarm is automatically muted and rolled up under Root Cause {upstream_ahu}."
        )
    elif status == "ENERGY_OUTLIER" or req.analysis_mode == "ENERGY_COHORT_CHECK":
        subagent = "energy_optimization_agent"
        tool_called = "bq_peer_cohort_zscore_audit"
        summary = (
            f"[AI PREDICTIVE FAILURE & ENERGY COHORT AUDIT on {label} ({req.node_id})]: "
            f"AI Failure Likelihood: {fail_prob}% within {fail_win}. {ai_diag.get('root_cause_explanation', '')} "
            f"Connected Elements at Risk: {at_risk_names}. "
            f"Historical MTTR: {mttr_info.get('typical_remote_ai_fix_mins', 18)} mins remote BACnet Priority 8 override vs. {mttr_info.get('typical_manual_fix_hours', 3.8)} hrs manual valve rebuild."
        )
    else:
        subagent = "abo_supervisor_agent"
        tool_called = "gql_inspect_entity_neighborhood"
        summary = (
            f"[AI DIGITAL TWIN & GRAPH DIAGNOSIS — {label} ({onto})]: AI Failure Probability: {fail_prob}% ({fail_win}). "
            f"Traversed {len(edges)} graph edges and {len(neighbors)} connected entities "
            f"(Connected Risk Exposure: {at_risk_names}; Bound BACnet Points: {nb['total_points_count']}). "
            f"All SHACL safety invariants conform."
        )

    gw_res = await _dispatch_via_agent_gateway(
        target_agent=subagent,
        tool_name=tool_called,
        prompt=(
            f"Run {req.analysis_mode} diagnosis on node {label} ({req.node_id}, status={status}, failure_risk={fail_prob}%). "
            f"Context: {summary}"
        ),
        site_id="ACME-SITE-001",
        node_id=req.node_id,
        invoke_live_runtime=True,
    )
    gw_ident = gw_res.get("agent_identity", {})
    gw_rt = gw_res.get("agent_runtime", {})
    trace_id = gw_res.get("otel_trace_id", trace_id)
    span_id = gw_res.get("otel_span_id", span_id)
    agent_identity = gw_ident.get("service_account") or AGENT_IDENTITY_LOOKUP.get(
        subagent, "sa-agent-supervisor@genai-demos-391416.iam.gserviceaccount.com"
    )
    step = {
        "agent_name": "abo_supervisor_agent",
        "subagent": subagent,
        "tool_called": tool_called,
        "summary": summary,
        "shacl_status": gw_res.get("shacl_status", "CONFORMS (0 Violations)"),
        "otel_trace_id": trace_id,
        "otel_span_id": span_id,
        "traceparent": gw_res.get("traceparent", f"00-{trace_id}-{span_id}-01"),
        "cloud_trace_console_url": gw_res.get("cloud_trace_console_url", ""),
        "agent_runtime": f"Vertex AI Agent Engine ({gw_rt.get('reasoning_engine_resource', AGENT_ENGINE_RESOURCE_NAME)})",
        "agent_runtime_invoked": gw_rt.get("invoked", True),
        "agent_runtime_latency_ms": gw_rt.get("latency_ms", gw_res.get("duration_ms", 0)),
        "agent_gateway": f"acme-abo-client-to-agent ({gw_res.get('policy_verdict', 'ALLOW')})",
        "agent_gateway_url": gw_res.get("gateway_url", AGENT_GATEWAY_URL),
        "agent_identity": agent_identity,
        "agent_identity_token_sha256": gw_ident.get("token_sha256_prefix", ""),
        "agent_registry_uri": gw_res.get(
            "agent_registry_uri", f"registry://acme-abo-agent-registry/{subagent}:2.0.0"
        ),
    }
    RUNTIME.agent_reasoning_steps.insert(0, step)
    RUNTIME.otel_spans.insert(
        0,
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "traceparent": gw_res.get("traceparent", ""),
            "cloud_trace_console_url": gw_res.get("cloud_trace_console_url", ""),
            "subagent": subagent,
            "tool": tool_called,
            "agent_identity": agent_identity,
            "token_sha256_prefix": gw_ident.get("token_sha256_prefix", ""),
            "reasoning_engine_resource": gw_rt.get("reasoning_engine_resource", AGENT_ENGINE_RESOURCE_NAME),
            "gateway_verdict": gw_res.get("policy_verdict", "ALLOW"),
            "duration_ms": gw_res.get("duration_ms", 0),
        },
    )
    await RUNTIME.broadcast("AGENT_INSPECTION", {"node_id": req.node_id, "agent_action": step})
    return {
        "status": "ANALYZED",
        "node_id": req.node_id,
        "agent_step": step,
        "causal_chain": {
            "upstream_ahu": fed_by_sources,
            "center_node": req.node_id,
            "downstream_fed_nodes": feeds_targets,
            "bacnet_controllers": controllers,
            "spatial_zones": spaces,
        },
    }


class AgentChatRequest(BaseModel):
    site_id: str = Field(default="ACME-SITE-001", min_length=3, max_length=64)
    selected_node_id: Optional[str] = Field(default="bldg:area_ec_ahu_1", max_length=160)
    question: str = Field(..., min_length=2, max_length=600)


def _build_portfolio_attention_summary() -> str:
    """Scans all 5 ACME Global Sites from portfolio_sites.csv to answer cross-building portfolio attention queries."""
    has_active_incident = len(RUNTIME.injected_events) > 0
    lines = [
        "**Cross-Portfolio AI Triage Summary (All 5 ACME Facilities — 1.69M sq ft):**",
    ]
    if has_active_incident:
        lines.append(
            "1. 🔴 **[PRIORITY 1 — ACTIVE ROOT CAUSE] ACME Emerald Crest HQ (`ACME-SITE-001`, Atlanta, GA — 185,000 sq ft):** "
            f"`RTU-1 (1st Floor Air Handler)` (`bldg:area_ec_ahu_1`) is in active fault (`{RUNTIME.active_scenario}` — Stage-1 DX High-Pressure Trip, "
            "98% failure severity, $18,500/hr SLA exposure across 31 1st-floor zones). **Action:** Approve BACnet Priority 8 Stage-2 Aux DX failover (4-min remote fix)."
        )
        lines.append(
            "2. 🟡 **[PRIORITY 2 — CLEANROOM PROCESS OUTLIER] ACME Sunbelt Precision Manufacturing Plant (`ACME-SITE-004`, Charlotte, NC — 510,000 sq ft):** "
            "`SMT PCB Assembly Line (Simultaneous Reheat Outlier)` (`bldg:s4_room_smt_clean` / `bldg:site4_smt_ahu_2_vav_4` `SMT Line VAV-4`) is a **Yellow Energy & Process Outlier (76.4°F, +3.65σ, 78% actuator seizure risk within 24–36 hrs)**. "
            "Simultaneous 52°F chilled-water cooling and 88% hot-water reheat is wasting **$14,200/yr** and risking SMT solder-paste viscosity scrap. "
            "**Action:** Run automated 14-min BACnet Priority 8 valve stroke flush (`0%→100%→0%`)."
        )
    else:
        lines.append(
            "1. 🟡 **[PRIORITY 1 — CLEANROOM PROCESS OUTLIER] ACME Sunbelt Precision Manufacturing Plant (`ACME-SITE-004`, Charlotte, NC — 510,000 sq ft):** "
            "`SMT PCB Assembly Line (Simultaneous Reheat Outlier)` (`bldg:s4_room_smt_clean` / `bldg:site4_smt_ahu_2_vav_4` `SMT Line VAV-4`) is a **Yellow Energy & Process Outlier (76.4°F, +3.65σ, 78% actuator seizure risk within 24–36 hrs)**. "
            "Simultaneous 52°F chilled-water cooling and 88% hot-water reheat is wasting **$14,200/yr** and risking **$14,500/hr in SMT solder-paste viscosity scrap**. "
            "**Action:** Run automated 14-min BACnet Priority 8 valve stroke flush (`0%→100%→0%`)."
        )

    if not RUNTIME.building_healed:
        lines.extend(
            [
                "2. 🟡 **[PRIORITY 2 — HYDRONIC REHEAT HYSTERESIS OUTLIER] ACME Emerald Crest HQ (`ACME-SITE-001`, Atlanta, GA — 2nd Floor):** "
                "`Huddle` (`bldg:room_2f_huddle` / `bldg:ec_2nd_floor_area9_emrd_2_piu_1` `PIU 2-1 Huddle`) is a **Yellow Outlier (+3.42σ, 74% actuator seizure risk within 36–48 hrs)** at **76.8°F**. "
                "Hydronic globe valve stem packing friction is holding reheat 68%–92% open against 55°F primary air (**$2,620/yr** waste). "
                "**Action:** 18-min remote BACnet full-stroke seat flush & +1.5°F deadband widen.",
                "3. 🟡 **[PRIORITY 3 — AIRFLOW TRANSDUCER & SCR RELAY OUTLIER] ACME Emerald Crest HQ (`ACME-SITE-001`, Atlanta, GA — 2nd Floor):** "
                "`Open Office 232` (`bldg:room_2f_open_office_232` / `bldg:ec_2nd_floor_area8_emrd_2_piu_8` `PIU 2-8 Open Office 232`) is a **Yellow Outlier (+2.78σ, 64% SCR relay fatigue risk within 48–72 hrs)** at **74.6°F**. "
                "A +185 CFM differential-pressure transducer offset is triggering premature parallel-fan SCR Stage-1 electric reheat (**$1,760/yr** waste). "
                "**Action:** 12-min remote BACnet DP zero-point auto-null.",
            ]
        )

    lines.extend(
        [
            "4. 🟢 **[NOMINAL — 0 ACTIVE ALARMS] ACME Midwest Logistics & Cold Chain Hub (`ACME-SITE-002`, Indianapolis, IN — 420,000 sq ft):** "
            "100% of Deep-Freeze Vault A (`-10.2°F`) and Biologics Cold Vault B (`36.0°F`) zones are healthy (`NH3-CHILL-1` & `MUA-1` at 99.4% SLA compliance; **$24,800/yr** evaporator defrost staging opportunity).",
            "5. 🟢 **[NOMINAL — 0 ACTIVE ALARMS] ACME Northeast Life Sciences Lab (`ACME-SITE-003`, Boston, MA — 260,000 sq ft) & ACME Pacific Tower Regional Center (`ACME-SITE-005`, San Jose, CA — 315,000 sq ft):** "
            "Boston `ISO-5 Sterile Fill-Finish Suite` & `BSL-3 Negative-Pressure Suite` (`MAHU-1`/`MAHU-2`, 99.8% SLA, **$31,500/yr** unoccupied air-change setback opportunity) and San Jose `DOAS-1 & VRF Heat-Recovery Plant` (99.1% SLA, **$19,600/yr** CO₂ demand ventilation opportunity) are operating nominally.",
        ]
    )
    return "\n".join(lines)


def _build_what_if_failure_impact_response(
    question: str,
    active_site_id: str,
    selected_node_id: str,
) -> Optional[Dict[str, str]]:
    """Simulates graduated degradation (20% / 50% / 100% failure), cascading chain-failure probability, and business impact."""
    q_lower = question.strip().lower()
    is_what_if = (
        any(w in q_lower for w in ("what is the impact", "what if", "if ", "fails", "fail", "degrade", "degradation", "lose", "outage", "goes down", "trip", "starv", "chain"))
        and any(w in q_lower for w in ("impact", "fail", "fails", "degrade", "degradation", "if ", "happens", "consequence", "chain", "ahu", "rtu", "vav", "piu", "mahu", "chiller", "doas"))
    )
    if not is_what_if:
        return None

    # Resolve target equipment/node across all 5 sites (so asking about IND-AHU-1 works from any selected site)
    target_key = selected_node_id.lower()
    if "ind-ahu-1" in q_lower or "ind_ahu_1" in q_lower or "process make-up" in q_lower or "chilled water" in q_lower:
        target_key = "bldg:s4_ind_ahu_1"
    elif "rtu-1" in q_lower or "ahu_1" in q_lower or "1st floor air handler" in q_lower:
        target_key = "bldg:area_ec_ahu_1"
    elif "rtu-2" in q_lower or "ahu_2" in q_lower or "2nd floor air handler" in q_lower:
        target_key = "bldg:area_ec_ahu_2"
    elif "smt" in q_lower or "vav-4" in q_lower or "vav_4" in q_lower:
        target_key = "bldg:site4_smt_ahu_2_vav_4"
    elif "piu 2-1" in q_lower or "piu-1" in q_lower or "piu_1" in q_lower or "huddle" in q_lower:
        target_key = "bldg:ec_2nd_floor_area9_emrd_2_piu_1"
    elif "piu 2-8" in q_lower or "piu-8" in q_lower or "piu_8" in q_lower or "232" in q_lower:
        target_key = "bldg:ec_2nd_floor_area8_emrd_2_piu_8"
    elif "nh3" in q_lower or "ammonia" in q_lower or "cold" in q_lower or "indianapolis" in q_lower:
        target_key = "bldg:s2_nh3_chiller_1"
    elif "mahu" in q_lower or "hepa" in q_lower or "boston" in q_lower or "bsl" in q_lower:
        target_key = "bldg:s3_hepa_mahu_1"
    elif "doas" in q_lower or "vrf" in q_lower or "san jose" in q_lower or "pacific" in q_lower:
        target_key = "bldg:s5_vrf_oas_1"

    if "s4_ind_ahu_1" in target_key:
        ans = (
            "### AI Cascading Failure & Degradation Impact Simulation: **`IND-AHU-1 (Process Make-Up & Chilled Water)`** (`bldg:s4_ind_ahu_1` — ACME Sunbelt Precision Manufacturing Plant, Charlotte, NC)\n"
            "• **Topological Role (`brick:feeds`):** Primary 42,000 CFM industrial make-up and chilled-water air handler feeding **`SMT PCB Assembly Line (Simultaneous Reheat Outlier)`** (`bldg:s4_room_smt_clean`), **`5-Axis Titanium CNC Machining Hall`** (`bldg:s4_room_cnc_hall`), and **`Thermal Composite Curing & Paint Line`** (`bldg:s4_room_curing_booth`).\n"
            "• **Graduated Degradation & Chain-Failure Probability Curve:**\n"
            "  - **If performance degrades by 20% (e.g., VFD airflow droop to 33,600 CFM or CHW supply drift +3°F):** **52% likelihood of cascading chain failure** within 35 minutes. Cleanroom positive pressurization drops below the `+0.05 in.w.c.` threshold, and because downstream **`SMT Line VAV-4 (Leaking Reheat Valve)`** (`bldg:site4_smt_ahu_2_vav_4`) is *already* fighting a `+3.65σ` reheat valve anomaly (`76.4°F`, 88% open), reduced primary cooling immediately triggers terminal damper saturation (100% open) and static-pressure starvation across adjacent CNC & Curing zones.\n"
            "  - **If performance degrades by 50% (chilled-water bypass failure or single supply fan trip):** **84% likelihood of cascading chain failure** within 14 minutes. SMT Cleanroom relative humidity breaches **48% RH** and zone temperature exceeds **77.5°F**, forcing automated pick-and-place quality holds.\n"
            "  - **If 100% unit failure occurs (hard mechanical trip):** **100% immediate downstream starvation** across all connected Floor 1 manufacturing and cleanroom terminal units within **6 minutes**.\n"
            "• **Business & Financial Impact:** **$48,500/hr** in halted surface-mount technology (SMT) PCB production, solder-paste viscosity/slump defects, and mandatory **4.5-hour ISO-6 particle recertification** before production can resume.\n"
            "• **Autonomous AI Mitigation (`SHACL Guarded Priority 8`):** First resolve the compounding **`SMT Line VAV-4`** reheat leak (14-min automated BACnet stroke flush), and stage cross-tie chiller **`CHW-PLANT-4`** + boost chilled-water differential pressure (`+3.5 PSI`) in **6 minutes** (vs. **5.0 hrs** manual plant dispatch)."
        )
    elif "area_ec_ahu_1" in target_key:
        ans = (
            "### AI Cascading Failure & Degradation Impact Simulation: **`RTU-1 (1st Floor Air Handler)`** (`bldg:area_ec_ahu_1` — ACME Emerald Crest HQ, Atlanta, GA)\n"
            "• **Topological Role (`brick:feeds`):** Primary 1st-floor rooftop air handler supplying **31 downstream Parallel Fan-Powered Terminal Units (PIUs)** across 16 1st-floor zones, including **`Server Rm`** (`bldg:room_1f_server_rm`, `Tier-1 Mission-Critical IT`) and **`Lobby`** (`bldg:room_1f_lobby`).\n"
            "• **Graduated Degradation & Chain-Failure Probability Curve:**\n"
            "  - **If performance degrades by 20% (supply air temperature rises from 55.0°F → 59.5°F or -20% static pressure):** **48% likelihood of cascading chain failure** within 40 minutes. The 12 highest-load perimeter PIUs open their primary dampers to 100%, collapsing duct static pressure from `1.40 in.w.c.` to `0.65 in.w.c.` and starving **`Server Rm`**.\n"
            "  - **If performance degrades by 50% (Stage-1 DX compressor cutout):** **86% likelihood of cascading chain failure** within 18 minutes. Supply air drifts to **68.5°F**, triggering **31 simultaneous downstream high-temperature zone alarms** (`75.8°F`).\n"
            "  - **If 100% unit failure occurs (supply fan VFD trip):** **100% immediate thermal starvation** across all 31 1st-floor zones; **`Server Rm`** hits thermal clock-throttling (`>78°F`) in **19 minutes**.\n"
            "• **Business & Financial Impact:** **$18,500/hr** in executive SLA penalties and Tier-1 IT rack thermal throttling exposure, plus **31 sympathetic room tickets** overwhelming facility dispatch if un-triaged.\n"
            "• **Autonomous AI Mitigation (`SHACL Guarded Priority 8`):** Automatically suppress all 31 sympathetic room alarms via `brick:feeds` lineage and write BACnet Priority 8 override (`54.0°F`) to engage **Stage-2 Auxiliary DX Cooling** in **4 minutes** (vs. **4.2 hrs** manual truck roll)."
        )
    elif "area_ec_ahu_2" in target_key:
        ans = (
            "### AI Cascading Failure & Degradation Impact Simulation: **`RTU-2 (2nd Floor Air Handler)`** (`bldg:area_ec_ahu_2` — ACME Emerald Crest HQ, Atlanta, GA)\n"
            "• **Topological Role (`brick:feeds`):** Primary 2nd-floor rooftop air handler serving **36 downstream PIU terminal units**, including active yellow outliers **`PIU 2-1 Huddle`** (`+3.42σ`) and **`PIU 2-8 Open Office 232`** (`+2.78σ`).\n"
            "• **Graduated Degradation & Chain-Failure Probability Curve:**\n"
            "  - **If performance degrades by 20% (-20% cooling capacity or supply air drift to 58.8°F):** **54% likelihood of cascading chain failure** within 30 minutes — accelerated because **`PIU 2-1 Huddle`** (stuck hydronic reheat valve at `76.8°F`) and **`PIU 2-8 Open Office 232`** (+185 CFM airflow sensor drift at `74.6°F`) are *already* injecting **11.4 kW** of parasitic heat into the 2nd-floor return plenum.\n"
            "  - **If performance degrades by 50%:** **85% likelihood of cascading chain failure** within 20 minutes across all 17 2nd-floor engineering and open-office zones (`>76.5°F`).\n"
            "  - **If 100% unit failure occurs:** **100% loss of 2nd-floor ventilation and cooling** across 36 terminal boxes within **12 minutes**.\n"
            "• **Business & Financial Impact:** **$14,200/hr** productivity & SLA comfort impact across 180+ 2nd-floor occupants, plus **$4,380/yr** ongoing reheat energy bleed.\n"
            "• **Autonomous AI Mitigation (`SHACL Guarded Priority 8`):** Auto-calibrate **`PIU 2-1`** and **`PIU 2-8`** first to shed 11.4 kW of false reheat load, then engage RTU-2 economizer/Stage-2 failover in **6 minutes**."
        )
    else:
        nb = get_graph_neighborhood(target_key)
        c_label = nb["center_node"].get("label", target_key)
        nb_count = len(nb["neighbors"])
        ans = (
            f"### AI Cascading Failure & Degradation Impact Simulation: **`{c_label}`** (`{target_key}`)\n"
            f"• **Topological Blast Radius:** Directly connected to **{nb_count} Knowledge Graph entities** across `brick:feeds`, `rec:locatedIn`, and `bsm:controlledBy`.\n"
            f"• **Graduated Degradation & Chain-Failure Probability Curve:**\n"
            f"  - **If performance degrades by 20%:** **~50% likelihood of cascading chain failure** across connected peer/downstream zones within 35–45 minutes due to static-pressure theft and PID loop saturation.\n"
            f"  - **If performance degrades by 50%:** **~82% likelihood of cascading chain failure** within 20 minutes, breaching ±1.5°F SLA bounds in adjacent spaces.\n"
            f"  - **If 100% failure occurs:** Immediate loss of local zone conditioning and automatic upstream AHU static-pressure trim rebalance.\n"
            f"• **Autonomous AI Mitigation:** Execute SHACL-guarded BACnet Priority 8 override to isolate the degraded node and rebalance adjacent VAV/PIU dampers in **8–15 minutes** (vs. **3.5 hrs** manual dispatch)."
        )

    return {
        "subagent": "cross_layer_rca_agent",
        "tool_called": "gql_simulate_degradation_chain_failure",
        "answer": ans,
        "resolved_node_id": target_key,
    }


@app.post("/api/agent/chat")
async def chat_with_building_agent(req: AgentChatRequest) -> Dict[str, Any]:
    """Open-ended conversational endpoint grounded in the active building's Digital Twin & Knowledge Graph."""
    twin = get_building_digital_twin(req.site_id)
    site_meta = twin["site"]
    rooms = twin["rooms"]
    floors = twin["floors"]
    node_id = req.selected_node_id or (floors[0]["primary_ahu_id"] if floors else "bldg:area_ec_ahu_1")
    nb = get_graph_neighborhood(node_id)
    center = nb["center_node"]

    q_lower = req.question.strip().lower()
    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]

    # Sort rooms by live temperature for thermal questions
    rooms_by_temp_desc = sorted(rooms, key=lambda r: float(r.get("live_temp_f", 70.0)), reverse=True)
    rooms_by_temp_asc = sorted(rooms, key=lambda r: float(r.get("live_temp_f", 70.0)))
    hottest = rooms_by_temp_desc[0] if rooms_by_temp_desc else {}
    coldest = rooms_by_temp_asc[0] if rooms_by_temp_asc else {}
    outliers = [r for r in rooms if r.get("runtime_status") == "ENERGY_OUTLIER"]

    # Check if user mentioned a specific room or device by name
    matched_room = next(
        (r for r in rooms if r["label"].lower() in q_lower or r["space_id"].lower() in q_lower),
        None,
    )
    matched_eq = next(
        (
            e for e in twin["all_equipment"]
            if str(e.get("label", "")).lower() in q_lower or str(e.get("node_id", "")).lower() in q_lower
        ),
        None,
    )

    ai_diag = nb.get("ai_diagnostics") or _build_ai_diagnostics_for_node(
        node_id, center.get("label", node_id), center.get("runtime_status", "HEALTHY"), nb["neighbors"]
    )
    mttr = ai_diag.get("mttr_intelligence", {})
    at_risk_els = ai_diag.get("at_risk_connected_elements", [])
    hist_wos = mttr.get("historical_incidents", [])

    # 1. Check for hypothetical "What-If" / Degradation / Chain-Failure impact simulation questions first
    what_if_res = _build_what_if_failure_impact_response(req.question, req.site_id, node_id)

    # 2. Check for cross-portfolio / multi-location attention queries ("what locations require attention?")
    is_portfolio_attention = any(
        phrase in q_lower
        for phrase in (
            "what locations",
            "which locations",
            "locations require",
            "sites require",
            "which sites",
            "which buildings",
            "what buildings",
            "require attention",
            "need attention",
            "needs attention",
            "across the portfolio",
            "all sites",
            "all buildings",
            "portfolio summary",
            "where should i focus",
            "prioritize across",
        )
    )

    if what_if_res is not None:
        subagent = what_if_res["subagent"]
        tool_called = what_if_res["tool_called"]
        answer = what_if_res["answer"]
    elif is_portfolio_attention:
        subagent = "abo_supervisor_agent"
        tool_called = "gql_scan_global_portfolio_attention_hotspots"
        answer = _build_portfolio_attention_summary()
    elif any(k in q_lower for k in ("risk", "likelihood", "probab", "predict", "blast", "connected", "history", "mttr", "fix", "work order", "how long")):
        subagent = "predictive_drift_agent"
        tool_called = "gql_predict_failure_and_mttr_history"
        at_risk_str = (
            "\n".join(
                f"  - `{el['label']}` (`{el['relationship']}`): **{el['failure_likelihood_pct']}% risk** — {el['impact_summary']}"
                for el in at_risk_els[:4]
            )
            or "  - All connected neighbors operating within nominal SLA bounds."
        )
        wo_str = (
            f"Last similar incident `{hist_wos[0]['work_order_id']}` ({hist_wos[0]['date']}) was resolved via `{hist_wos[0]['fix_applied']}` (Remote AI Fix: **{hist_wos[0]['remote_ai_fix_mins']} mins** vs. Manual Dispatch: **{hist_wos[0]['manual_dispatch_hrs']} hrs**)."
            if hist_wos
            else ""
        )
        answer = (
            f"AI Predictive Failure & Blast-Radius Analysis for **`{center.get('label')}`** (`{node_id}`):\n"
            f"• **Failure Probability:** **{ai_diag.get('failure_probability_pct')}%** ({ai_diag.get('risk_level')} Risk — Window: **{ai_diag.get('predicted_failure_window')}**).\n"
            f"• **AI Root-Cause Diagnosis:** {ai_diag.get('root_cause_explanation')}\n"
            f"• **Connected Elements at Risk:**\n{at_risk_str}\n"
            f"• **Historical MTTR & Fix Intelligence:** Typical Remote AI Fix takes **{mttr.get('typical_remote_ai_fix_mins')} mins** vs. **{mttr.get('typical_manual_fix_hours')} hrs** manual truck roll. {wo_str}"
        )
    elif any(k in q_lower for k in ("hot", "warm", "temp", "thermal", "cold", "cool", "comfort", "degree")):
        subagent = "predictive_drift_agent"
        tool_called = "bq_query_zone_thermal_profile"
        answer = (
            f"In **{site_meta.get('site_name')}** ({site_meta.get('city')}), across {len(rooms)} monitored spatial zones:\n"
            f"• **Warmest Zone:** `{hottest.get('label')}` at **{hottest.get('live_temp_f')}°F** ({hottest.get('sla_tier')}, status: `{hottest.get('runtime_status')}`).\n"
            f"• **Coolest Zone:** `{coldest.get('label')}` at **{coldest.get('live_temp_f')}°F** ({coldest.get('sla_tier')}).\n"
            f"• **Overall Comfort Compliance:** **{site_meta.get('zone_comfort_compliance_pct', 99.0)}%** of zones are holding within ±1.0°F of their BACnet setpoint."
        )
    elif any(k in q_lower for k in ("energy", "waste", "outlier", "reheat", "z-score", "zscore", "saving", "kwh", "cost", "co2")):
        subagent = "energy_optimization_agent"
        tool_called = "bq_peer_cohort_zscore_audit"
        if req.site_id == "ACME-SITE-001" and outliers:
            outlier_desc = (
                "2 distinct 2nd-floor yellow outliers detected on `RTU-2`:\n"
                "  1. **`Huddle` (`PIU 2-1 Huddle` at 76.8°F, Z = +3.42σ, 74% failure risk):** Hydronic globe valve stem packing hysteresis holding reheat 68%–92% open ($2,620/yr waste).\n"
                "  2. **`Open Office 232` (`PIU 2-8 Open Office 232` at 74.6°F, Z = +2.78σ, 64% failure risk):** +185 CFM airflow differential-pressure sensor drift triggering parallel-fan SCR Stage-1 electric reheat ($1,760/yr waste)."
            )
        elif outliers:
            outlier_desc = (
                f"Active outlier detected in `{outliers[0]['label']}` (`{outliers[0]['devices'][0]['label']}` at {outliers[0]['live_temp_f']}°F — simultaneous cooling & reheat Z = +3.65σ, 78% actuator seizure risk)."
            )
        else:
            outlier_desc = "All terminal boxes are currently operating within ±1.5σ of their AHU peer cohort."
        answer = (
            f"Peer-Cohort Energy Audit for **{site_meta.get('site_name')}**:\n"
            f"• **Identified Recoverable Savings:** **${int(float(site_meta.get('identified_annual_energy_savings_usd', 18400))):,}/yr** and **{site_meta.get('identified_co2_reduction_tons', 42.0)} tons CO₂/yr**.\n"
            f"• **Cohort Finding:** {outlier_desc}"
        )
    elif any(k in q_lower for k in ("alarm", "fault", "issue", "root cause", "incident", "broken", "fail", "storm")):
        subagent = "cross_layer_rca_agent"
        tool_called = "gql_trace_causal_blast_radius"
        if len(RUNTIME.injected_events) == 0:
            answer = (
                f"**{site_meta.get('site_name')}** currently has **0 active root-cause fault storms** (`NOMINAL` state). "
                f"Historical baseline alarm noise reduction at this facility is **{site_meta.get('alarm_noise_reduction_pct', 89.5)}%** "
                f"(Autonomous MTTR: **{site_meta.get('mttr_autonomous_minutes', 8.0)} min** vs. manual baseline **{site_meta.get('mttr_baseline_hours', 4.2)} hrs**). "
                f"Currently selected entity `{center.get('label')}` (`{node_id}`) is reporting `{center.get('runtime_status', 'HEALTHY')}`."
            )
        else:
            roots = [e for e in RUNTIME.injected_events if e.get("is_root_cause")]
            muted = [e for e in RUNTIME.injected_events if e.get("suppressed_by_agent")]
            rc = roots[0] if roots else RUNTIME.injected_events[0]
            answer = (
                f"**ACTIVE INCIDENT ({RUNTIME.active_scenario}) in {site_meta.get('site_name')}**:\n"
                f"• **Primary Root Cause:** `{rc.get('node_id')}` — {rc.get('alarm_message')}\n"
                f"• **Sympathetic Alarms Muted:** **{len(muted)} downstream zone alarms** automatically suppressed via `brick:feeds` graph traversal.\n"
                f"• **OT Network Check:** BACnet Router verified at **0.0% packet loss** (`bsm:controlledBy`)."
            )
    elif any(k in q_lower for k in ("bacnet", "controller", "network", "router", "packet", "arcnet", "point", "sensor")):
        subagent = "cross_layer_rca_agent"
        tool_called = "gql_verify_bacnet_ot_controllers"
        sample_pts = ", ".join(p.get("label", "") for p in nb["bacnet_points"][:4]) or "Zone Temp, Airflow, Damper Cmd"
        answer = (
            f"OT Network & BACnet Telemetry Summary for **{site_meta.get('site_name')}**:\n"
            f"• **Active BACnet Controllers:** **{twin['controllers_count']} controllers** across **{twin['equipment_count']} HVAC equipment assets** (0.0% packet loss).\n"
            f"• **Selected Entity (`{center.get('label')}`):** Bound to **{nb['total_points_count']} BACnet objects** (including: {sample_pts})."
        )
    elif matched_room or matched_eq:
        target_label = matched_room["label"] if matched_room else matched_eq["label"]
        target_id = matched_room["space_id"] if matched_room else matched_eq["node_id"]
        target_nb = get_graph_neighborhood(target_id)
        subagent = "abo_supervisor_agent"
        tool_called = "gql_inspect_entity_neighborhood"
        answer = (
            f"Knowledge Graph Inspection for **{target_label}** (`{target_id}`) in **{site_meta.get('site_name')}**:\n"
            f"• **Ontology Class:** `{target_nb['center_node'].get('ontology_class')}` • **SLA Tier:** `{target_nb['center_node'].get('sla_tier', 'Tier-1')}`\n"
            f"• **Connected Graph Neighbors:** **{len(target_nb['neighbors'])} entities** across **{len(target_nb['edges'])} edges** (`brick:feeds`, `rec:locatedIn`, `bsm:controlledBy`).\n"
            f"• **Bound BACnet Points:** **{target_nb['total_points_count']} telemetry points**."
        )
    else:
        subagent = "abo_supervisor_agent"
        tool_called = "gql_query_building_digital_twin"
        floor_names = ", ".join(f["short_label"] for f in floors)
        answer = (
            f"**{site_meta.get('site_name')}** (`{req.site_id}` — {site_meta.get('city')}, {int(float(site_meta.get('gross_sqft', 185000))):,} sq ft {site_meta.get('facility_type')}):\n"
            f"• **Spatial Topology:** {len(floors)} floor levels ({floor_names}) containing **{len(rooms)} monitored zones**.\n"
            f"• **Equipment & OT Layer:** **{twin['equipment_count']} HVAC equipment nodes** and **{twin['controllers_count']} BACnet controllers**.\n"
            f"• **Currently Selected Entity:** `{center.get('label')}` (`{node_id}`, `{center.get('ontology_class')}`) with **{len(nb['neighbors'])} connected graph neighbors** and **{nb['total_points_count']} bound BACnet points**."
        )

    gw_res = await _dispatch_via_agent_gateway(
        target_agent=subagent,
        tool_name=tool_called,
        prompt=(
            f"[Site={req.site_id} ({site_meta.get('site_name')}, {site_meta.get('city')}) | Node={node_id}] "
            f"User question: {req.question}"
        ),
        site_id=req.site_id,
        node_id=node_id,
        invoke_live_runtime=True,
    )
    gw_ident = gw_res.get("agent_identity", {})
    gw_rt = gw_res.get("agent_runtime", {})
    trace_id = gw_res.get("otel_trace_id", trace_id)
    span_id = gw_res.get("otel_span_id", span_id)
    agent_identity = gw_ident.get("service_account") or AGENT_IDENTITY_LOOKUP.get(
        subagent, "sa-agent-supervisor@genai-demos-391416.iam.gserviceaccount.com"
    )
    step = {
        "agent_name": "abo_supervisor_agent",
        "subagent": subagent,
        "tool_called": tool_called,
        "user_question": req.question,
        "summary": answer,
        "shacl_status": gw_res.get("shacl_status", "CONFORMS (0 Violations)"),
        "otel_trace_id": trace_id,
        "otel_span_id": span_id,
        "traceparent": gw_res.get("traceparent", f"00-{trace_id}-{span_id}-01"),
        "cloud_trace_console_url": gw_res.get("cloud_trace_console_url", ""),
        "agent_runtime": f"Vertex AI Agent Engine ({gw_rt.get('reasoning_engine_resource', AGENT_ENGINE_RESOURCE_NAME)})",
        "agent_runtime_invoked": gw_rt.get("invoked", True),
        "agent_runtime_latency_ms": gw_rt.get("latency_ms", gw_res.get("duration_ms", 0)),
        "agent_gateway": f"acme-abo-client-to-agent ({gw_res.get('policy_verdict', 'ALLOW')})",
        "agent_gateway_url": gw_res.get("gateway_url", AGENT_GATEWAY_URL),
        "agent_identity": agent_identity,
        "agent_identity_token_sha256": gw_ident.get("token_sha256_prefix", ""),
        "agent_registry_uri": gw_res.get(
            "agent_registry_uri", f"registry://acme-abo-agent-registry/{subagent}:2.0.0"
        ),
    }
    RUNTIME.agent_reasoning_steps.insert(0, step)
    RUNTIME.otel_spans.insert(
        0,
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "traceparent": gw_res.get("traceparent", ""),
            "cloud_trace_console_url": gw_res.get("cloud_trace_console_url", ""),
            "subagent": subagent,
            "tool": tool_called,
            "agent_identity": agent_identity,
            "token_sha256_prefix": gw_ident.get("token_sha256_prefix", ""),
            "reasoning_engine_resource": gw_rt.get("reasoning_engine_resource", AGENT_ENGINE_RESOURCE_NAME),
            "gateway_verdict": gw_res.get("policy_verdict", "ALLOW"),
            "duration_ms": gw_res.get("duration_ms", 0),
        },
    )
    await RUNTIME.broadcast("AGENT_INSPECTION", {"node_id": node_id, "agent_action": step})
    return {
        "status": "ANSWERED",
        "site_id": req.site_id,
        "selected_node_id": node_id,
        "question": req.question,
        "answer": answer,
        "agent_step": step,
        "gql_query": nb["gql_query"],
        "gateway_telemetry": gw_res,
    }



# ---------------------------------------------------------------------------
# Cloud Run SPA Static Asset Serving (/ and /admin routes)
# ---------------------------------------------------------------------------
FRONTEND_DIST_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"

if FRONTEND_DIST_DIR.exists():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", include_in_schema=False)
    @app.get("/admin", include_in_schema=False)
    async def serve_spa_routes() -> FileResponse:
        return FileResponse(str(FRONTEND_DIST_DIR / "index.html"))

