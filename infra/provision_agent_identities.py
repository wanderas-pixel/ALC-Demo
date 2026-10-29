"""Provisions and verifies the 7 cryptographic Agent Identity Service Accounts, IAM bindings,
and GCS staging bucket in `genai-demos-391416` for ACME Co. Autonomous Building Operations."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Dict, List, Set

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")
REGION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET_NAME = f"{PROJECT_ID}-acme-abo-building-exports"

SERVICE_ACCOUNTS: Dict[str, str] = {
    "sa-abo-agent-gateway": "ACME ABO Agent Gateway Ingress/Egress Policy & OTel Proxy Identity",
    "sa-agent-supervisor": "ACME ABO Agent Identity — Root Supervisor Agent (abo_supervisor_agent)",
    "sa-agent-triage": "ACME ABO Agent Identity — Alarm Triage & Storm Dedup Agent (alarm_triage_agent)",
    "sa-agent-rca": "ACME ABO Agent Identity — Cross-Layer RCA Agent (cross_layer_rca_agent)",
    "sa-agent-energy": "ACME ABO Agent Identity — Energy & Drift Optimizer Agent (energy_optimization_agent)",
    "sa-agent-remediation": "ACME ABO Agent Identity — HITL BACnet Priority-8 Remediation Agent (remediation_dispatch_agent)",
    "sa-cockpit-cloudrun": "ACME ABO Cloud Run Operations Cockpit & BFF SA",
}

REQUIRED_ROLES: List[str] = [
    "roles/aiplatform.user",
    "roles/cloudtrace.agent",
    "roles/monitoring.metricWriter",
    "roles/logging.logWriter",
    "roles/bigquery.dataViewer",
    "roles/bigquery.jobUser",
    "roles/iam.serviceAccountTokenCreator",
    "roles/run.invoker",
]


def run_cmd(args: List[str]) -> str:
    res = subprocess.run(args, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed ({' '.join(args)}): {res.stderr}")
    return res.stdout


def main() -> None:
    print(f"[1/3] Checking existing Service Accounts in {PROJECT_ID}...")
    existing_out = run_cmd(
        ["gcloud", "iam", "service-accounts", "list", "--project", PROJECT_ID, "--format=json"]
    )
    existing_emails: Set[str] = {
        item.get("email", "") for item in json.loads(existing_out)
    }

    for sa_id, display_name in SERVICE_ACCOUNTS.items():
        email = f"{sa_id}@{PROJECT_ID}.iam.gserviceaccount.com"
        if email in existing_emails:
            print(f"  ✓ Service Account exists: {email}")
        else:
            print(f"  + Creating Service Account: {email}...")
            run_cmd(
                [
                    "gcloud",
                    "iam",
                    "service-accounts",
                    "create",
                    sa_id,
                    "--display-name",
                    display_name,
                    "--project",
                    PROJECT_ID,
                ]
            )
            print(f"  ✓ Created: {email}")

    print(f"[2/3] Verifying IAM Roles for Agent Identities in {PROJECT_ID}...")
    policy_out = run_cmd(
        ["gcloud", "projects", "get-iam-policy", PROJECT_ID, "--format=json"]
    )
    policy = json.loads(policy_out)
    role_to_members: Dict[str, Set[str]] = {}
    for b in policy.get("bindings", []):
        role_to_members[b["role"]] = set(b.get("members", []))

    for sa_id in SERVICE_ACCOUNTS:
        member = f"serviceAccount:{sa_id}@{PROJECT_ID}.iam.gserviceaccount.com"
        for role in REQUIRED_ROLES:
            if member in role_to_members.get(role, set()):
                continue
            print(f"  + Binding {role} -> {member}...")
            run_cmd(
                [
                    "gcloud",
                    "projects",
                    "add-iam-policy-binding",
                    PROJECT_ID,
                    "--member",
                    member,
                    "--role",
                    role,
                    "--condition=None",
                    "--quiet",
                ]
            )

    print(f"[3/3] Verifying GCS Staging Bucket gs://{BUCKET_NAME}...")
    b_check = subprocess.run(
        ["gcloud", "storage", "buckets", "describe", f"gs://{BUCKET_NAME}", "--project", PROJECT_ID],
        capture_output=True,
        text=True,
        check=False,
    )
    if b_check.returncode == 0:
        print(f"  ✓ Bucket exists: gs://{BUCKET_NAME}")
    else:
        print(f"  + Creating bucket gs://{BUCKET_NAME} in {REGION}...")
        run_cmd(
            [
                "gcloud",
                "storage",
                "buckets",
                "create",
                f"gs://{BUCKET_NAME}",
                "--project",
                PROJECT_ID,
                "--location",
                REGION,
                "--uniform-bucket-level-access",
            ]
        )
        print(f"  ✓ Created bucket: gs://{BUCKET_NAME}")

    print("All 7 Agent Identities, IAM Roles, and Staging Bucket verified!")


if __name__ == "__main__":
    main()

