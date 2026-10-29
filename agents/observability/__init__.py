"""OpenTelemetry observability package for ACME Co. Autonomous Building Operations."""

from .otel_setup import (
    AGENT_IDENTITY_MAP,
    RECENT_OTEL_SPANS,
    init_agent_otel,
    record_otel_span,
    traced_tool_span,
)

__all__ = [
    "AGENT_IDENTITY_MAP",
    "RECENT_OTEL_SPANS",
    "init_agent_otel",
    "record_otel_span",
    "traced_tool_span",
]

