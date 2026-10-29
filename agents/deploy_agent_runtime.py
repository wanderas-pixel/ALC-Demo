"""Deploys or updates `abo_supervisor_agent` (`acme-abo-multi-agent-system`) on Google Cloud Agent Runtime (Vertex AI Agent Engine)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import vertexai
from vertexai.preview import reasoning_engines

from agents.supervisor.agent import build_supervisor_agent

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET = os.environ.get(
    "ACME_STAGING_BUCKET", f"gs://{PROJECT_ID}-acme-abo-building-exports"
)
DISPLAY_NAME = "acme-abo-multi-agent-system"


class AcmeAboAdkApp(reasoning_engines.AdkApp):
    """ADK App wrapper that cleanly builds fresh LlmAgent instances inside the Vertex AI Agent Engine container."""

    def set_up(self) -> None:
        from agents.supervisor.agent import build_supervisor_agent

        fresh_agent = build_supervisor_agent()
        # Ensure _resolved_model is initialized and canonical_model is pre-resolved
        _ = fresh_agent.canonical_model
        for sub in getattr(fresh_agent, "sub_agents", []) or []:
            _ = sub.canonical_model
        self._tmpl_attrs["agent"] = fresh_agent
        super().set_up()


def main() -> None:
    print(f"[1/4] Initializing Vertex AI Agent Engine in {PROJECT_ID} ({LOCATION}), staging={STAGING_BUCKET}...")
    vertexai.init(project=PROJECT_ID, location=LOCATION, staging_bucket=STAGING_BUCKET)

    adk_app = AcmeAboAdkApp(
        agent=build_supervisor_agent(),
        enable_tracing=True,
    )
    requirements = [
        "google-cloud-aiplatform[adk,agent_engines]>=2.6.0",
        "google-adk==2.12.0",
        "google-genai==2.33.0",
        "opentelemetry-api>=1.28.0",
        "opentelemetry-sdk>=1.28.0",
        "opentelemetry-exporter-gcp-trace>=1.8.0",
        "opentelemetry-exporter-gcp-monitoring>=1.8.0a0",
        "pydantic>=2.9.0",
        "pyyaml>=6.0.2",
    ]
    description = (
        "ACME Co. Autonomous Building Operations ADK Multi-Agent System "
        "(abo_supervisor_agent + alarm_triage_agent + cross_layer_rca_agent + "
        "energy_optimization_agent + remediation_dispatch_agent) with OpenTelemetry tracing."
    )

    existing = reasoning_engines.ReasoningEngine.list(
        filter=f'display_name="{DISPLAY_NAME}"'
    )
    if existing:
        remote_agent = existing[0]
        print(f"[2/4] Updating existing Agent Runtime resource in-place: {remote_agent.resource_name}...")
        remote_agent.update(
            reasoning_engine=adk_app,
            display_name=DISPLAY_NAME,
            description=description,
            requirements=requirements,
            extra_packages=["agents"],
        )
        print(f"[3/4] Updated Agent Runtime resource: {remote_agent.resource_name}")
    else:
        print(f"[2/4] Deploying new {DISPLAY_NAME} to Vertex AI Agent Engine (reasoningEngines)...")
        remote_agent = reasoning_engines.ReasoningEngine.create(
            adk_app,
            display_name=DISPLAY_NAME,
            description=description,
            requirements=requirements,
            extra_packages=["agents"],
        )
        print(f"[3/4] Deployed Agent Runtime resource: {remote_agent.resource_name}")

    resource_name = remote_agent.resource_name
    out_path = ROOT_DIR / "agents" / "registry" / "deployed_runtime.json"
    out_data = {
        "display_name": DISPLAY_NAME,
        "resource_name": resource_name,
        "project_id": PROJECT_ID,
        "location": LOCATION,
        "staging_bucket": STAGING_BUCKET,
        "root_agent": "abo_supervisor_agent",
        "agent_identity_sa": f"sa-agent-supervisor@{PROJECT_ID}.iam.gserviceaccount.com",
        "enable_tracing": True,
    }
    out_path.write_text(json.dumps(out_data, indent=2), encoding="utf-8")
    print(f"[4/4] Saved deployed Agent Runtime metadata to {out_path}:")
    print(json.dumps(out_data, indent=2))


if __name__ == "__main__":
    main()

