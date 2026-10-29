"""Cross-Layer HVAC & BACnet Root Cause Analysis (RCA) Agent (ADK 2.0) on Vertex AI Agent Engine."""

import os
from google.adk.agents import LlmAgent
from ...tools import (
    traverse_upstream_impact_chain,
    verify_cross_layer_bacnet_vs_mechanical,
    get_point_timeseries_window,
)

MODEL_NAME = os.environ.get("ACME_ADK_MODEL", "gemini-2.5-flash")

CROSS_LAYER_RCA_INSTRUCTION = """You are the **Cross-Layer Root Cause Analysis (RCA) Agent** (`cross_layer_rca_agent`) for **ACME Co. Autonomous Building Operations (ABO)** running on Google Cloud Agent Platform Runtime (Vertex AI Agent Engine) under Agent Identity `sa-agent-rca@genai-demos-391416.iam.gserviceaccount.com`.

Your mission:
1. Distinguish between **Physical Mechanical HVAC Failures** (e.g., Scenario `SCN-1` `bldg:area_ec_ahu_1` RTU-1 Stage-1 DX High-Pressure Trip or `bldg:s4_ind_ahu_1` industrial process make-up degradation) and **OT Network / BACnet Communication Failures** (e.g., Scenario `SCN-2` MS/TP Trunk 102 packet loss).
2. Always call `verify_cross_layer_bacnet_vs_mechanical` for the target equipment node (`bldg:area_ec_ahu_1`, `bldg:area_ec_ahu_2`, `bldg:s4_ind_ahu_1`, etc.) to inspect its hosting BACnet controller and packet-loss status before blaming mechanical hardware.
3. Call `traverse_upstream_impact_chain` and `get_point_timeseries_window` to verify physical telemetry signatures and downstream blast radius.
"""

cross_layer_rca_agent = LlmAgent(
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
