"""Root Supervisor Agent for ACME Co. Autonomous Building Operations (ABO) on Agent Platform Runtime (Vertex AI Agent Engine)."""

import os
from google.adk.agents import LlmAgent
from ..observability.otel_setup import init_agent_otel
from ..subagents.alarm_triage.agent import ALARM_TRIAGE_INSTRUCTION
from ..subagents.cross_layer_rca.agent import CROSS_LAYER_RCA_INSTRUCTION
from ..subagents.energy_optimizer.agent import ENERGY_OPTIMIZER_INSTRUCTION
from ..subagents.remediation_dispatch.agent import REMEDIATION_DISPATCH_INSTRUCTION
from ..tools import (
    traverse_upstream_impact_chain,
    verify_cross_layer_bacnet_vs_mechanical,
    query_active_alarms_and_root_causes,
    get_point_timeseries_window,
    detect_peer_cohort_zscore_anomalies,
    evaluate_timeseries_forecast_and_drift,
    propose_safe_bacnet_write_property,
    create_work_order_ticket,
)

# Initialize full OpenTelemetry (OTel) tracing & metrics for Agent Platform Runtime
init_agent_otel("acme-abo-agent-platform-runtime")

MODEL_NAME = os.environ.get("ACME_ADK_MODEL", "gemini-2.5-flash")

SUPERVISOR_INSTRUCTION = """You are the **ACME Building Operations Supervisor Agent** (`abo_supervisor_agent`) orchestrating autonomous diagnostics, root-cause isolation, predictive thermal protection, and safe BACnet remediation across the **ACME Co.** 5-building global portfolio (1.69M sq ft).

Official 5-Building ACME Portfolio (NEVER mention any other cities or buildings):
1. `ACME-SITE-001`: **ACME Emerald Crest HQ** (Atlanta, GA — 185,000 sq ft, Peak AI Risk: 74% on `PIU 2-1 Huddle` `bldg:ec_2nd_floor_area9_emrd_2_piu_1` at 76.8°F +3.42σ, and 64% on `PIU 2-8 Open Office 232` `bldg:ec_2nd_floor_area8_emrd_2_piu_8` at 74.6°F +2.78σ).
2. `ACME-SITE-002`: **ACME Midwest Logistics & Cold Chain Hub** (Indianapolis, IN — 420,000 sq ft, Peak AI Risk: 8% on `NH3-CHILL-1`, Nominal 0 active alarms).
3. `ACME-SITE-003`: **ACME Northeast Life Sciences Lab** (Boston, MA — 260,000 sq ft, Peak AI Risk: 6% on `MAHU-1`, Nominal 0 active alarms).
4. `ACME-SITE-004`: **ACME Sunbelt Precision Manufacturing Plant** (Charlotte, NC — 510,000 sq ft, Peak AI Risk: 78% on `SMT Line VAV-4` `bldg:site4_smt_ahu_2_vav_4` in `SMT PCB Assembly Line` `bldg:s4_room_smt_clean` at 76.4°F +3.65σ).
5. `ACME-SITE-005`: **ACME Pacific Tower Regional Center** (San Jose, CA — 315,000 sq ft, Peak AI Risk: 5% on `DOAS-1`, Nominal 0 active alarms).

Agent Platform Architecture & Governance:
- **Runtime:** Running on **Google Cloud Agent Platform Runtime / Vertex AI Agent Engine** (`acme-abo-agent-platform-runtime`).
- **Gateway:** All North-South (UI/BFF) and East-West (A2A subagent & tool) traffic is mediated by **Agent Gateway** (`acme-abo-agent-gateway`).
- **Identity:** You operate under cryptographic **Agent Identity** `sa-agent-supervisor@genai-demos-391416.iam.gserviceaccount.com` and delegate tasks to subagents with scoped per-agent identities.
- **Registry:** Subagents and their capabilities are discovered dynamically via **Agent Registry** (`acme-abo-agent-registry`).
- **Observability:** Every subagent handoff, BigQuery GQL/SQL query, and SHACL safety validation emits **OpenTelemetry (OTel)** spans (`CloudTraceSpanExporter` + `CloudMonitoringMetricsExporter`) with W3C `traceparent` context propagation.

You coordinate four specialist subagents registered in **Agent Registry** and have direct access to grounded BigQuery Property Graph (GQL) and BigQuery Time-Series tools:
1. `alarm_triage_agent` (`sa-agent-triage`): Deduplicates cascading alarm storms (`SCN-1` RTU-1 failure where 1 root-cause fault triggers 31 sympathetic downstream zone alarms) and scans portfolio attention hotspots.
2. `cross_layer_rca_agent` (`sa-agent-rca`): Separates physical HVAC mechanical faults from BACnet/IP & ARCNET/MS-TP transport dropouts.
3. `energy_optimization_agent` (`sa-agent-energy`): Detects peer-cohort z-score anomalies (`PIU 2-1 Huddle`, `PIU 2-8 Open Office 232`, `SMT Line VAV-4`) and runs TimesFM 2.5 predictive thermal breach forecasts.
4. `remediation_dispatch_agent` (`sa-agent-remediation`): Stages SHACL-validated BACnet `WriteProperty` overrides at Priority 8 (enforced by **Agent Gateway** and requiring Human-in-the-Loop approval) and dispatches CMMS work orders.
"""


def build_supervisor_agent() -> LlmAgent:
    """Builds a fresh ADK 2.0 LlmAgent hierarchy for Vertex AI Agent Engine runtime."""
    triage = LlmAgent(
        name="alarm_triage_agent",
        model=MODEL_NAME,
        description=(
            "Deduplicates sympathetic BAS alarm storms into a single root-cause incident "
            "by traversing Brick v1.4 and BACnet graph topology across the 5 ACME facilities."
        ),
        instruction=ALARM_TRIAGE_INSTRUCTION,
        tools=[
            query_active_alarms_and_root_causes,
            traverse_upstream_impact_chain,
        ],
    )
    rca = LlmAgent(
        name="cross_layer_rca_agent",
        model=MODEL_NAME,
        description=(
            "Performs cross-layer root cause analysis across Brick v1.4 mechanical HVAC "
            "assets and BACnet/IP & ARCNET/MS-TP network controllers."
        ),
        instruction=CROSS_LAYER_RCA_INSTRUCTION,
        tools=[
            traverse_upstream_impact_chain,
            verify_cross_layer_bacnet_vs_mechanical,
            get_point_timeseries_window,
        ],
    )
    energy = LlmAgent(
        name="energy_optimization_agent",
        model=MODEL_NAME,
        description=(
            "Detects peer-cohort z-score telemetry outliers, simultaneous heating/cooling waste, "
            "and predictive thermal breaches using BigQuery AI time-series tools on Agent Platform Runtime."
        ),
        instruction=ENERGY_OPTIMIZER_INSTRUCTION,
        tools=[
            detect_peer_cohort_zscore_anomalies,
            evaluate_timeseries_forecast_and_drift,
            get_point_timeseries_window,
        ],
    )
    remediation = LlmAgent(
        name="remediation_dispatch_agent",
        model=MODEL_NAME,
        description=(
            "Stages SHACL-validated BACnet WriteProperty overrides at Priority 8 with Human-in-the-Loop "
            "approval and creates automated CMMS field work orders."
        ),
        instruction=REMEDIATION_DISPATCH_INSTRUCTION,
        tools=[
            propose_safe_bacnet_write_property,
            create_work_order_ticket,
        ],
    )
    return LlmAgent(
        name="abo_supervisor_agent",
        model=MODEL_NAME,
        description=(
            "ACME Co. Autonomous Building Operations Supervisor Agent (ADK 2.0) running on "
            "Google Cloud Agent Platform Runtime (Vertex AI Agent Engine) with Agent Gateway, "
            "Agent Identity, Agent Registry, and full OpenTelemetry observability."
        ),
        instruction=SUPERVISOR_INSTRUCTION,
        sub_agents=[triage, rca, energy, remediation],
        tools=[
            traverse_upstream_impact_chain,
            verify_cross_layer_bacnet_vs_mechanical,
            query_active_alarms_and_root_causes,
            get_point_timeseries_window,
            detect_peer_cohort_zscore_anomalies,
            evaluate_timeseries_forecast_and_drift,
            propose_safe_bacnet_write_property,
            create_work_order_ticket,
        ],
    )


abo_supervisor_agent = build_supervisor_agent()

# ADK 2.0 root_agent export
root_agent = abo_supervisor_agent
