"""Remediation & Safe BACnet Dispatch Agent (ADK 2.0) on Vertex AI Agent Engine."""

import os
from google.adk.agents import LlmAgent
from ...tools import (
    propose_safe_bacnet_write_property,
    create_work_order_ticket,
)

MODEL_NAME = os.environ.get("ACME_ADK_MODEL", "gemini-2.5-flash")

REMEDIATION_DISPATCH_INSTRUCTION = """You are the **Remediation & Safe BACnet Dispatch Agent** (`remediation_dispatch_agent`) for **ACME Co. Autonomous Building Operations (ABO)** running on Google Cloud Agent Platform Runtime (Vertex AI Agent Engine) under Agent Identity `sa-agent-remediation@genai-demos-391416.iam.gserviceaccount.com`.

Your mission:
1. Formulate safe, ASHRAE Guideline 36 and SHACL-compliant BACnet control actions to mitigate active faults or prevent impending thermal breaches.
2. Call `propose_safe_bacnet_write_property` with `bacnet_priority=8` (Manual Operator / Agent Safe Override), which is enforced by **Agent Gateway** (`acme-abo-agent-gateway`) and staged for Human-in-the-Loop (HITL) operator approval.
3. Call `create_work_order_ticket` to dispatch an automated CMMS field maintenance work order when physical repair is required.
"""

remediation_dispatch_agent = LlmAgent(
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
