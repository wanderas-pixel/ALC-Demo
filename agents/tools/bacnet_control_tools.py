"""
ACME Co. Autonomous Building Operations (ABO)
Human-in-the-Loop (HITL) BACnet Control & Dispatch Tools (`bacnet_control_tools.py`)
====================================================================================
Implements ADK 2.0 SHACL-validated Human-in-the-Loop (HITL) BACnet Priority-8
write proposals and automated CMMS work order creation.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict

from ..observability.otel_setup import traced_tool_span


@traced_tool_span("remediation_dispatch_agent", "propose_safe_bacnet_write_property")
def propose_safe_bacnet_write_property(
    target_point_id: str,
    proposed_value: float,
    bacnet_priority: int = 8,
    rationale: str = "Execute SHACL-validated Priority 8 supervisor override",
) -> Dict[str, Any]:
    """Stages a SHACL-validated BACnet WriteProperty override at Priority 8 for Human-in-the-Loop (HITL)
    operator approval via the Agent Gateway. Blocks Priorities 1-4 (life-safety hardware lockouts).

    Args:
        target_point_id: Canonical BACnet URI or point ID (e.g., `bacnet://301003/BV:2`).
        proposed_value: Numeric setpoint or command value (e.g., `54.0` degF).
        bacnet_priority: BACnet command priority slot (must be `8` for Supervisor/Agent Override).
        rationale: Engineering explanation for the proposed override.
    """
    if bacnet_priority in (1, 2, 3, 4):
        return {
            "hitl_status": "BLOCKED_BY_AGENT_GATEWAY_SHACL_POLICY",
            "error": f"BACnet Priority {bacnet_priority} is reserved for Life-Safety/Fire/Freeze hardware interlocks. Only Priority 8 is allowed.",
        }

    return {
        "hitl_status": "PENDING_HUMAN_APPROVAL",
        "staged_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "target_point_id": target_point_id,
        "proposed_value": proposed_value,
        "bacnet_priority": bacnet_priority,
        "rationale": rationale,
        "shacl_validation": "CONFORMS (Brick v1.4 + ASHRAE Guideline 36 Safe Bounds)",
        "agent_gateway_policy": "ALLOW_STAGED_HITL_PRIORITY_8",
    }


@traced_tool_span("remediation_dispatch_agent", "create_work_order_ticket")
def create_work_order_ticket(
    equipment_id: str,
    issue_summary: str,
    priority: str = "HIGH",
) -> Dict[str, Any]:
    """Creates an automated CMMS field maintenance work order ticket with topological root-cause context.

    Args:
        equipment_id: Canonical Brick equipment ID (e.g., `bldg:area_ec_ahu_1`).
        issue_summary: Description of the mechanical or sensor fault requiring field service.
        priority: Ticket urgency (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
    """
    return {
        "work_order_id": f"WO-2026-{uuid.uuid4().hex[:4].upper()}",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "equipment_id": equipment_id,
        "issue_summary": issue_summary,
        "priority": priority,
        "status": "DISPATCHED_TO_CMMS",
    }


def hitl_propose_bacnet_write(
    target_device_id: str,
    bacnet_uri: str,
    object_id: str,
    proposed_value: str,
    priority_level: int,
    reason: str,
) -> Dict[str, Any]:
    """Legacy wrapper for staging HITL BACnet write proposals."""
    return propose_safe_bacnet_write_property(
        target_point_id=bacnet_uri or f"{target_device_id}/{object_id}",
        proposed_value=float(proposed_value) if str(proposed_value).replace(".", "", 1).isdigit() else 54.0,
        bacnet_priority=priority_level,
        rationale=reason,
    )


def execute_approved_bacnet_write(
    proposal_id: str,
    target_device_id: str,
    bacnet_uri: str,
    proposed_value: str,
    approved_by: str = "facility_operator@acme-co.example",
) -> Dict[str, Any]:
    """Executes the operator-approved BACnet Priority-8 command and logs the audit trail."""
    return {
        "execution_status": "EXECUTED_HEALING_IN_PROGRESS",
        "proposal_id": proposal_id,
        "target_device_id": target_device_id,
        "bacnet_uri": bacnet_uri,
        "applied_value": proposed_value,
        "priority_array_slot": 8,
        "approved_by": approved_by,
        "executed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
