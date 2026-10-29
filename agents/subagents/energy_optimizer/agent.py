"""Energy & Peer-Cohort Drift Optimizer Agent (ADK 2.0) on Vertex AI Agent Engine."""

import os
from google.adk.agents import LlmAgent
from ...tools import (
    detect_peer_cohort_zscore_anomalies,
    evaluate_timeseries_forecast_and_drift,
    get_point_timeseries_window,
)

MODEL_NAME = os.environ.get("ACME_ADK_MODEL", "gemini-2.5-flash")

ENERGY_OPTIMIZER_INSTRUCTION = """You are the **Energy & Peer-Cohort Drift Optimizer Agent** (`energy_optimization_agent`) for **ACME Co. Autonomous Building Operations (ABO)** running on Google Cloud Agent Platform Runtime (Vertex AI Agent Engine) under Agent Identity `sa-agent-energy@genai-demos-391416.iam.gserviceaccount.com`.

Your mission:
1. Call `detect_peer_cohort_zscore_anomalies` to compare peer equipment cohorts across the 5 ACME sites and flag yellow outliers where `|z_score| >= 2.2`:
   - `ACME-SITE-001` (Atlanta, GA — 2nd Floor): `PIU 2-1 Huddle` (`bldg:ec_2nd_floor_area9_emrd_2_piu_1` in `bldg:room_2f_huddle`, 76.8°F, +3.42σ, 74% failure risk, $2,620/yr waste, 18-min AI Fix vs 3.8h truck roll) and `PIU 2-8 Open Office 232` (`bldg:ec_2nd_floor_area8_emrd_2_piu_8` in `bldg:room_2f_open_office_232`, 74.6°F, +2.78σ, 64% failure risk, $1,760/yr waste, 12-min AI Fix vs 2.5h truck roll).
   - `ACME-SITE-004` (Charlotte, NC — 1st Floor): `SMT Line VAV-4` (`bldg:site4_smt_ahu_2_vav_4` in `bldg:s4_room_smt_clean`, 76.4°F, +3.65σ, 78% failure risk, $14,200/yr waste, 14-min AI Fix vs 4.5h truck roll).
2. Call `evaluate_timeseries_forecast_and_drift` to run TimesFM 2.5 (`AI.FORECAST` / `AI.DETECT_ANOMALIES`) trajectory projection and graduated degradation curves (20% / 50% / 100%).
"""

energy_optimization_agent = LlmAgent(
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

energy_optimizer_agent = energy_optimization_agent
