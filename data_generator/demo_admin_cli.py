#!/usr/bin/env python3
"""
ACME Co. Autonomous Building Operations (ABO)
Companion Admin CLI (`demo_admin_cli.py`)
=========================================
Allows triggering Option A (Cascading Rooftop Unit Failure — SCN-1),
Option B (Critical Server Room Predictive Alert — SCN-4), or Instant Demo Reset (<1s)
from the command line against the FastAPI BFF (mirroring the `/admin` Chrome Tab).

Usage:
  python3 demo_admin_cli.py --action status
  python3 demo_admin_cli.py --action inject --scenario OPTION_A_SCN1_CASCADING_RTU1_FAILURE
  python3 demo_admin_cli.py --action inject --scenario OPTION_B_SCN4_SERVER_ROOM_PREDICTIVE_SLA
  python3 demo_admin_cli.py --action reset
"""

import argparse
import json
import urllib.request
import urllib.error


def main() -> None:
    parser = argparse.ArgumentParser(description="ACME ABO Demo Director CLI")
    parser.add_argument(
        "--url",
        default="http://localhost:8080",
        help="Base URL of the ACME ABO FastAPI BFF (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--action",
        choices=["status", "inject", "reset", "preload_all"],
        default="status",
        help="Admin action to execute",
    )
    parser.add_argument(
        "--scenario",
        choices=[
            "OPTION_A_SCN1_CASCADING_RTU1_FAILURE",
            "OPTION_B_SCN4_SERVER_ROOM_PREDICTIVE_SLA",
            "OPTIONAL_SCN2_MSTP102_BUS_STORM",
            "OPTIONAL_SCN3_SILENT_ENERGY_BLEED",
        ],
        default="OPTION_A_SCN1_CASCADING_RTU1_FAILURE",
        help="Scenario key to inject when --action=inject",
    )
    parser.add_argument(
        "--mode",
        choices=["wave", "instant"],
        default="wave",
        help="Wave streaming mode ('wave' streams across timed waves; 'instant' emits all waves immediately)",
    )
    args = parser.parse_args()

    if args.action == "status":
        endpoint = f"{args.url}/api/admin/state"
        req = urllib.request.Request(endpoint, method="GET")
    elif args.action == "reset":
        endpoint = f"{args.url}/api/admin/reset"
        req = urllib.request.Request(
            endpoint,
            data=json.dumps({"reason": "CLI Reset to Clean T=0 Baseline"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    elif args.action == "preload_all":
        endpoint = f"{args.url}/api/admin/preload-all"
        req = urllib.request.Request(
            endpoint,
            data=json.dumps({}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    else:
        endpoint = f"{args.url}/api/admin/inject"
        req = urllib.request.Request(
            endpoint,
            data=json.dumps({"scenario_key": args.scenario, "mode": args.mode}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            print(json.dumps(body, indent=2))
    except urllib.error.URLError as exc:
        print(f"[INFO] BFF server at {args.url} not currently running ({exc}).")
        print(f"       When the server is running, this command invokes: {endpoint}")


if __name__ == "__main__":
    main()

