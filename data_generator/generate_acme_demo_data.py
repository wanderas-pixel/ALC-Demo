#!/usr/bin/env python3
"""
ACME Co. Autonomous Building Operations (ABO) — Synthetic Data & Scenario Generator
====================================================================================
Reads the resolved semantic ontology (`ec_building_brick.ttl`) and deterministically
generates the complete set of BigQuery Property Graph tables, SVWEB.DATASOURCES metadata,
28-day 15-minute time-series telemetry (940,800 rows), and BAS alarm/override logs (360 rows)
incorporating the 4 Golden Demo Scenarios and exact statistical baselines from `floor_view.html`
and `network_topology.html`.

Pure Python 3 standard library implementation (zero external dependencies).
"""

import csv
import datetime
import json
import math
import os
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
TTL_PATH = BASE_DIR / "ec_building_brick.ttl"
OUT_DIR = Path(__file__).resolve().parent


def clean_brand(text: str) -> str:
    """Neutralizes vendor/customer brand strings to ACME Co. equivalents."""
    if not text:
        return ""
    replacements = [
        ("ALC EC Building", "ACME Emerald Crest HQ"),
        ("RTU-1 (ALC)", "RTU-1 (ACME)"),
        ("RTU-2 (ALC)", "RTU-2 (ACME)"),
        ("RTU 1 (ALC)", "RTU 1 (ACME)"),
        ("RTU 2 (ALC)", "RTU 2 (ACME)"),
        ("(Carrier)", "(ACME OEM)"),
        ("Router: 03 Carrier", "Router: 03 ACME"),
        ("carrier_rtu", "acme_rtu"),
        ("Carrier", "ACME"),
        ("carrier", "acme"),
        ("WebCTRL", "BAS Core"),
    ]
    out = text
    for old, new in replacements:
        out = out.replace(old, new)
    return out


def parse_ttl(ttl_path: Path) -> Dict[str, Dict[str, Any]]:
    """Parses `ec_building_brick.ttl` into a dictionary of subject blocks."""
    raw = clean_brand(ttl_path.read_text(encoding="utf-8"))
    blocks = [
        b.strip()
        for b in raw.split("\n\n")
        if b.strip() and not b.strip().startswith("@prefix")
    ]
    entities: Dict[str, Dict[str, Any]] = {}

    for block in blocks:
        m = re.match(r"^(\S+)\s+a\s+([^;]+?)\s*([;.])", block, re.DOTALL)
        if not m:
            continue
        subj = m.group(1).strip()
        rdf_types = [t.strip() for t in m.group(2).split(",")]

        def get_single(pred: str) -> str:
            pat = rf"{re.escape(pred)}\s+\"([^\"]+)\""
            found = re.search(pat, block)
            return found.group(1) if found else ""

        def get_uri_list(pred: str) -> List[str]:
            # Match predicate up to next `;` or `.` at end of statement
            pat = rf"{re.escape(pred)}\s+([^\";]+?)\s*[;.]"
            found = re.search(pat, block, re.DOTALL)
            if not found:
                return []
            items = [x.strip() for x in found.group(1).split(",")]
            return [x for x in items if x and not x.startswith("[")]

        # Check for blank nodes (`ref:hasExternalReference`)
        ts_ref: Dict[str, str] = {}
        ts_match = re.search(
            r"\[\s*a\s+ref:TimeseriesReference\s*;([^\]]+)\]", block, re.DOTALL
        )
        if ts_match:
            ts_body = ts_match.group(1)
            for k, p in [
                ("timeseries_id", "ref:hasTimeseriesId"),
                ("match_basis", "bsm:matchBasis"),
                ("match_status", "bsm:matchStatus"),
                ("newest_sample", "bsm:newestSample"),
                ("oldest_sample", "bsm:oldestSample"),
                ("series_table", "bsm:seriesTable"),
            ]:
                pm = re.search(rf"{re.escape(p)}\s+\"([^\"]+)\"", ts_body)
                if pm:
                    ts_ref[k] = pm.group(1)
            rc_m = re.search(r"bsm:recordCount\s+(\d+)", ts_body)
            if rc_m:
                ts_ref["record_count"] = rc_m.group(1)

        bac_ref: Dict[str, str] = {}
        bac_match = re.search(
            r"\[\s*a\s+ref:BACnetReference\s*;([^\]]+)\]", block, re.DOTALL
        )
        if bac_match:
            bac_body = bac_match.group(1)
            for k, p in [
                ("object_identifier", "bacnet:object-identifier"),
                ("object_type", "bacnet:object-type"),
                ("bacnet_uri", "ref:BACnetURI"),
            ]:
                pm = re.search(rf"{re.escape(p)}\s+\"([^\"]+)\"", bac_body)
                if pm:
                    bac_ref[k] = pm.group(1)
            obj_of = re.search(r"bacnet:objectOf\s+(\S+)", bac_body)
            if obj_of:
                bac_ref["object_of"] = obj_of.group(1).rstrip(";").strip()

        unit_m = re.search(r"brick:hasUnit\s+(\S+)", block)
        unit_val = unit_m.group(1).rstrip(";,.") if unit_m else ""

        entities[subj] = {
            "subject": subj,
            "rdf_types": rdf_types,
            "label": clean_brand(get_single("rdfs:label")),
            "raw_label": get_single("rdfs:label"),
            "comment": clean_brand(get_single("rdfs:comment")),
            "dbid": get_single("bsm:webctrlDbid"),
            "path": get_single("bsm:webctrlPath"),
            "template": get_single("bsm:template"),
            "program": get_single("bsm:program"),
            "class_rule": get_single("bsm:classRule"),
            "class_rule_source": get_single("bsm:classRuleSource"),
            "class_confidence": get_single("bsm:classConfidence"),
            "floor_basis": get_single("bsm:floorBasis"),
            "core_evidence": clean_brand(get_single("bsm:coreEvidence")),
            "point_ref": get_single("bsm:webctrlPointRef"),
            "bacnet_block": get_single("bsm:bacnetBlock"),
            "unit_source": get_single("bsm:unitSource"),
            "unit": unit_val,
            "has_location": get_uri_list("brick:hasLocation"),
            "is_part_of": get_uri_list("brick:isPartOf"),
            "has_part": get_uri_list("brick:hasPart"),
            "rec_includes": get_uri_list("rec:includes"),
            "feeds": get_uri_list("brick:feeds"),
            "has_point": get_uri_list("brick:hasPoint"),
            "controller": get_uri_list("bsm:controller"),
            "runs_program": get_uri_list("bsm:runsProgram"),
            "on_network": get_uri_list("bsm:onNetwork"),
            "routes_to": get_uri_list("bsm:routesTo"),
            "behind_router": get_uri_list("bsm:behindRouter"),
            "controller_model": get_single("bsm:controllerModel"),
            "controller_name": clean_brand(get_single("bsm:controllerName")),
            "device_type": get_single("bsm:deviceType"),
            "mac_address": get_single("bsm:macAddress"),
            "media_type": get_single("bsm:mediaType"),
            "network_name": get_single("bsm:network"),
            "network_number": get_single("bsm:networkNumber"),
            "serial_number": get_single("bsm:serialNumber"),
            "ip_address": get_single("bsm:ipAddress"),
            "subnet_mask": get_single("bsm:subnetMask"),
            "default_gateway": get_single("bsm:defaultGateway"),
            "physical_shape": get_single("bsm:physicalShape"),
            "physical_shape_basis": get_single("bsm:physicalShapeBasis"),
            "compile_type": get_single("bsm:compileType"),
            "ts_ref": ts_ref,
            "bac_ref": bac_ref,
        }
    return entities


# Exact room assignments & comfort/occupancy metrics from floor_view.html
ROOM_CATALOG: List[Tuple[str, str, str, str, float, float]] = [
    # (room_id, room_name, floor_id, sla_tier, daytime_occ_pct, comfort_pct)
    ("bldg:room_1f_server_rm", "ISS Server Room", "bldg:ec_1st_floor", "Tier-1 Mission Critical", 15.0, 100.0),
    ("bldg:room_1f_nsa_office", "NSA Office", "bldg:ec_1st_floor", "Tier-2 Customer Facing", 48.0, 99.2),
    ("bldg:room_1f_lobby", "Lobby", "bldg:ec_1st_floor", "Tier-2 Customer Facing", 62.0, 100.0),
    ("bldg:room_1f_oem", "OEM", "bldg:ec_1st_floor", "Tier-3 Standard Office", 44.0, 100.0),
    ("bldg:room_1f_7_11", "7-11", "bldg:ec_1st_floor", "Tier-2 Customer Facing", 51.0, 88.0),
    ("bldg:room_1f_nsa_cubes", "NSA Cubes", "bldg:ec_1st_floor", "Tier-3 Standard Office", 55.0, 96.0),
    ("bldg:room_1f_nsa_offices", "NSA Offices", "bldg:ec_1st_floor", "Tier-3 Standard Office", 46.0, 98.5),
    ("bldg:room_1f_restrooms", "Restrooms", "bldg:ec_1st_floor", "Tier-3 Standard Office", 32.0, 99.0),
    ("bldg:room_1f_break_room", "Break Room", "bldg:ec_1st_floor", "Tier-3 Standard Office", 38.0, 99.1),
    ("bldg:room_1f_alcs_tpi", "ALCS/TPI", "bldg:ec_1st_floor", "Tier-3 Standard Office", 41.0, 99.4),
    ("bldg:room_1f_nsa_copier", "NSA Copier", "bldg:ec_1st_floor", "Tier-3 Standard Office", 29.0, 99.5),
    ("bldg:room_1f_show_case", "Show Case", "bldg:ec_1st_floor", "Tier-2 Customer Facing", 36.0, 99.0),
    ("bldg:room_1f_nsa", "NSA", "bldg:ec_1st_floor", "Tier-3 Standard Office", 42.0, 99.2),
    ("bldg:room_1f_oem_conf", "OEM Conf", "bldg:ec_1st_floor", "Tier-2 Customer Facing", 34.0, 99.3),
    ("bldg:room_1f_oem_lab", "OEM Lab", "bldg:ec_1st_floor", "Tier-2 Customer Facing", 49.0, 99.0),
    ("bldg:room_1f_offices_vav10", "Offices (VAV 10)", "bldg:ec_1st_floor", "Tier-3 Standard Office", 39.0, 99.4),
    ("bldg:room_1f_new_conf", "New Conference Room", "bldg:ec_1st_floor", "Tier-2 Customer Facing", 35.0, 99.6),
    ("bldg:room_2f_open_office_201a", "Open Office 201A", "bldg:ec_2nd_floor", "Tier-3 Standard Office", 17.0, 97.5),
    ("bldg:room_2f_open_office_202", "Open Office 202", "bldg:ec_2nd_floor", "Tier-3 Standard Office", 42.0, 98.8),
    ("bldg:room_2f_open_office_203", "Open Office 203", "bldg:ec_2nd_floor", "Tier-3 Standard Office", 45.0, 98.9),
    ("bldg:room_2f_open_office_203a", "Open Office 203A", "bldg:ec_2nd_floor", "Tier-3 Standard Office", 38.0, 98.7),
    ("bldg:room_2f_break_recording", "Break/Recording", "bldg:ec_2nd_floor", "Tier-3 Standard Office", 0.0, 98.5),
    ("bldg:room_2f_open_seating_228", "Open Seating 228", "bldg:ec_2nd_floor", "Tier-3 Standard Office", 33.0, 98.2),
    ("bldg:room_2f_open_office_232", "Open Office 232", "bldg:ec_2nd_floor", "Tier-3 Standard Office", 41.0, 98.0),
    ("bldg:room_2f_conf_230_airport", "Conference 230 Airport", "bldg:ec_2nd_floor", "Tier-2 Customer Facing", 34.0, 99.0),
    ("bldg:room_2f_office_231", "Office 231", "bldg:ec_2nd_floor", "Tier-3 Standard Office", 36.0, 99.1),
    ("bldg:room_2f_offices_233_235", "Offices 233-235", "bldg:ec_2nd_floor", "Tier-3 Standard Office", 27.0, 98.6),
    ("bldg:room_2f_huddle", "Huddle", "bldg:ec_2nd_floor", "Tier-2 Customer Facing", 14.0, 96.8),
    ("bldg:room_2f_office_225", "Office 225", "bldg:ec_2nd_floor", "Tier-3 Standard Office", 19.0, 98.9),
    ("bldg:room_2f_conf_226_hotel_cal", "Conference 226 Hotel Cal", "bldg:ec_2nd_floor", "Tier-2 Customer Facing", 27.0, 98.7),
    ("bldg:room_2f_open_office_221", "Open Office 221", "bldg:ec_2nd_floor", "Tier-3 Standard Office", 44.0, 99.0),
    ("bldg:room_2f_breakout", "Breakout", "bldg:ec_2nd_floor", "Tier-3 Standard Office", 12.0, 98.4),
    ("bldg:room_2f_conf_218", "Conference 218", "bldg:ec_2nd_floor", "Tier-2 Customer Facing", 31.0, 99.0),
    ("bldg:room_2f_training_univ", "Training Univ", "bldg:ec_2nd_floor", "Tier-2 Customer Facing", 40.0, 98.9),
]


def infer_room_for_equipment(eq_id: str, label: str, floor_id: str) -> str:
    """Maps an equipment node to one of the 34 REC Room entities based on its label/ID."""
    lbl_lower = label.lower()
    if "server" in lbl_lower or "server_rm" in eq_id:
        return "bldg:room_1f_server_rm"
    mapping = [
        ("7-11", "bldg:room_1f_7_11"),
        ("nsa offices", "bldg:room_1f_nsa_offices"),
        ("nsa office", "bldg:room_1f_nsa_office"),
        ("lobby", "bldg:room_1f_lobby"),
        ("oem conf", "bldg:room_1f_oem_conf"),
        ("oem lab", "bldg:room_1f_oem_lab"),
        ("oem", "bldg:room_1f_oem"),
        ("nsa cubes", "bldg:room_1f_nsa_cubes"),
        ("restrooms", "bldg:room_1f_restrooms"),
        ("break room", "bldg:room_1f_break_room"),
        ("alcs/tpi", "bldg:room_1f_alcs_tpi"),
        ("nsa copier", "bldg:room_1f_nsa_copier"),
        ("show case", "bldg:room_1f_show_case"),
        ("vav 5 (nsa)", "bldg:room_1f_nsa"),
        ("vav 10", "bldg:room_1f_offices_vav10"),
        ("new conference", "bldg:room_1f_new_conf"),
        ("201a", "bldg:room_2f_open_office_201a"),
        ("202", "bldg:room_2f_open_office_202"),
        ("203a", "bldg:room_2f_open_office_203a"),
        ("203", "bldg:room_2f_open_office_203"),
        ("break/recording", "bldg:room_2f_break_recording"),
        ("228", "bldg:room_2f_open_seating_228"),
        ("232", "bldg:room_2f_open_office_232"),
        ("230", "bldg:room_2f_conf_230_airport"),
        ("231", "bldg:room_2f_office_231"),
        ("233-235", "bldg:room_2f_offices_233_235"),
        ("huddle", "bldg:room_2f_huddle"),
        ("225", "bldg:room_2f_office_225"),
        ("226", "bldg:room_2f_conf_226_hotel_cal"),
        ("221", "bldg:room_2f_open_office_221"),
        ("breakout", "bldg:room_2f_breakout"),
        ("218", "bldg:room_2f_conf_218"),
        ("training", "bldg:room_2f_training_univ"),
    ]
    for key, r_id in mapping:
        if key in lbl_lower:
            return r_id
    if floor_id == "bldg:ec_1st_floor":
        return "bldg:room_1f_nsa_cubes"
    if floor_id == "bldg:ec_2nd_floor":
        return "bldg:room_2f_open_office_202"
    return ""


def generate_all() -> None:
    random.seed(42)
    print(f"[1/7] Parsing seed RDF/Turtle ontology: {TTL_PATH.name} ...")
    entities = parse_ttl(TTL_PATH)

    points_raw: Dict[str, Dict[str, Any]] = {}
    equip_raw: Dict[str, Dict[str, Any]] = {}
    ctrl_raw: Dict[str, Dict[str, Any]] = {}
    net_raw: Dict[str, Dict[str, Any]] = {}
    prog_raw: Dict[str, Dict[str, Any]] = {}
    space_raw: Dict[str, Dict[str, Any]] = {}

    for subj, data in entities.items():
        rtypes = data["rdf_types"]
        if "__" in subj:
            points_raw[subj] = data
        elif any(
            t in ("bsm:Controller", "bsm:Router", "bacnet:BACnetDevice", "bsm:InferredNetworkDevice")
            for t in rtypes
        ):
            ctrl_raw[subj] = data
        elif "bsm:Network" in rtypes:
            net_raw[subj] = data
        elif "bsm:Program" in rtypes:
            prog_raw[subj] = data
        elif any(
            t in ("brick:Building", "brick:Floor", "brick:Space", "brick:Room", "rec:Room", "brick:Collection")
            for t in rtypes
        ):
            space_raw[subj] = data
        elif "bsm:TimeseriesDatabase" in rtypes:
            continue
        else:
            equip_raw[subj] = data

    # Build reverse map: point -> equipment, and equipment -> serving AHU
    point_to_equip: Dict[str, str] = {}
    equip_has_trend: Dict[str, bool] = {eq: False for eq in equip_raw}
    serving_ahu_map: Dict[str, str] = {}

    for eq_id, eq_data in equip_raw.items():
        for pt_id in eq_data["has_point"]:
            point_to_equip[pt_id] = eq_id
        for fed_eq in eq_data["feeds"]:
            serving_ahu_map[fed_eq] = eq_id

    for pt_id, pt_data in points_raw.items():
        eq_id = point_to_equip.get(pt_id, pt_id.split("__")[0])
        point_to_equip[pt_id] = eq_id
        if pt_data["ts_ref"]:
            equip_has_trend[eq_id] = True

    # -------------------------------------------------------------------------
    # 1. portfolio_sites.csv (5 rows)
    # -------------------------------------------------------------------------
    print("[2/7] Generating portfolio_sites.csv (5 sites) ...")
    portfolio_rows = [
        {
            "site_id": "ACME-SITE-001",
            "site_name": "ACME Emerald Crest HQ (Hero Site)",
            "city": "Atlanta, GA",
            "facility_type": "Commercial R&D & Corporate Campus",
            "gross_sqft": 185000,
            "floors_count": 2,
            "equipment_count": 126,
            "bacnet_controllers_count": 90,
            "active_raw_alarms": 38,
            "correlated_incidents": 4,
            "alarm_noise_reduction_pct": 89.5,
            "mttr_baseline_hours": 4.2,
            "mttr_autonomous_minutes": 8.0,
            "zone_comfort_compliance_pct": 99.0,
            "identified_annual_energy_savings_usd": 18400,
            "identified_co2_reduction_tons": 42.0,
            "sla_status": "AT_RISK_PREDICTIVE",
        },
        {
            "site_id": "ACME-SITE-002",
            "site_name": "ACME Midwest Logistics & Cold Chain Hub",
            "city": "Indianapolis, IN",
            "facility_type": "Industrial Cold Storage & Distribution",
            "gross_sqft": 420000,
            "floors_count": 1,
            "equipment_count": 214,
            "bacnet_controllers_count": 148,
            "active_raw_alarms": 19,
            "correlated_incidents": 2,
            "alarm_noise_reduction_pct": 89.5,
            "mttr_baseline_hours": 5.1,
            "mttr_autonomous_minutes": 11.0,
            "zone_comfort_compliance_pct": 99.6,
            "identified_annual_energy_savings_usd": 46200,
            "identified_co2_reduction_tons": 98.5,
            "sla_status": "HEALTHY",
        },
        {
            "site_id": "ACME-SITE-003",
            "site_name": "ACME Northeast Life Sciences Lab",
            "city": "Boston, MA",
            "facility_type": "Cleanroom & Biopharma R&D",
            "gross_sqft": 260000,
            "floors_count": 4,
            "equipment_count": 310,
            "bacnet_controllers_count": 240,
            "active_raw_alarms": 11,
            "correlated_incidents": 1,
            "alarm_noise_reduction_pct": 90.9,
            "mttr_baseline_hours": 3.8,
            "mttr_autonomous_minutes": 7.5,
            "zone_comfort_compliance_pct": 99.8,
            "identified_annual_energy_savings_usd": 31900,
            "identified_co2_reduction_tons": 64.2,
            "sla_status": "HEALTHY",
        },
        {
            "site_id": "ACME-SITE-004",
            "site_name": "ACME Sunbelt Precision Manufacturing Plant",
            "city": "Charlotte, NC",
            "facility_type": "Industrial Manufacturing",
            "gross_sqft": 510000,
            "floors_count": 2,
            "equipment_count": 285,
            "bacnet_controllers_count": 195,
            "active_raw_alarms": 24,
            "correlated_incidents": 3,
            "alarm_noise_reduction_pct": 87.5,
            "mttr_baseline_hours": 4.7,
            "mttr_autonomous_minutes": 9.5,
            "zone_comfort_compliance_pct": 98.4,
            "identified_annual_energy_savings_usd": 54800,
            "identified_co2_reduction_tons": 118.0,
            "sla_status": "WARNING_ENERGY_DRIFT",
        },
        {
            "site_id": "ACME-SITE-005",
            "site_name": "ACME Pacific Tower Regional Center",
            "city": "San Jose, CA",
            "facility_type": "Class-A Commercial Office",
            "gross_sqft": 315000,
            "floors_count": 6,
            "equipment_count": 198,
            "bacnet_controllers_count": 152,
            "active_raw_alarms": 8,
            "correlated_incidents": 1,
            "alarm_noise_reduction_pct": 87.5,
            "mttr_baseline_hours": 3.9,
            "mttr_autonomous_minutes": 6.5,
            "zone_comfort_compliance_pct": 99.4,
            "identified_annual_energy_savings_usd": 22700,
            "identified_co2_reduction_tons": 39.4,
            "sla_status": "HEALTHY",
        },
    ]
    write_csv(OUT_DIR / "portfolio_sites.csv", portfolio_rows)

    # -------------------------------------------------------------------------
    # 2. equipment_nodes.csv (126 rows)
    # -------------------------------------------------------------------------
    print("[3/7] Generating equipment_nodes.csv (126 rows), spatial_nodes.csv (38 rows), network_and_controller_nodes.csv (100 rows) ...")
    equip_rows: List[Dict[str, Any]] = []
    room_to_equip_list: Dict[str, List[str]] = {r[0]: [] for r in ROOM_CATALOG}

    for eq_id in sorted(equip_raw.keys()):
        d = equip_raw[eq_id]
        brick_cls = d["rdf_types"][0] if d["rdf_types"] else "brick:Equipment"
        # Map to 223P equivalent class
        if "Rooftop_Unit" in brick_cls:
            s223_cls = "s223:AirHandlingUnit"
        elif "Fan_Coil_Unit" in brick_cls:
            s223_cls = "s223:FanCoilUnit"
        elif "Variable_Air_Volume_Box" in brick_cls:
            s223_cls = (
                "s223:FanPoweredTerminal"
                if "piu" in eq_id.lower()
                else "s223:SingleDuctTerminal"
            )
        else:
            s223_cls = "s223:Equipment"

        loc = d["has_location"][0] if d["has_location"] else (d["is_part_of"][0] if d["is_part_of"] else "")
        if "1st_floor" in eq_id or loc == "bldg:ec_1st_floor":
            floor_id = "bldg:ec_1st_floor"
        elif "2nd_floor" in eq_id or loc.startswith("bldg:ec_2nd_floor"):
            floor_id = "bldg:ec_2nd_floor"
        elif loc == "bldg:area" or "ahu" in eq_id or "rtu" in eq_id:
            floor_id = "bldg:area"
        else:
            floor_id = loc or "bldg:building"

        room_id = infer_room_for_equipment(eq_id, d["label"], floor_id)
        if room_id and room_id in room_to_equip_list:
            room_to_equip_list[room_id].append(eq_id)

        equip_rows.append(
            {
                "node_id": eq_id,
                "site_id": "ACME-SITE-001",
                "brick_class": brick_cls,
                "ashrae_223p_class": s223_cls,
                "label": d["label"],
                "dbid": d["dbid"],
                "geographic_path": d["path"],
                "floor_id": floor_id,
                "room_id": room_id,
                "serving_ahu_id": serving_ahu_map.get(eq_id, ""),
                "controller_id": d["controller"][0] if d["controller"] else "",
                "program_id": d["runs_program"][0] if d["runs_program"] else "",
                "program_name": d["program"],
                "template": d["template"],
                "class_rule": d["class_rule"],
                "class_rule_source": d["class_rule_source"],
                "class_confidence": d["class_confidence"] or "high",
                "floor_basis": d["floor_basis"] or "explicit-tree-path",
                "core_evidence": d["core_evidence"],
                "point_count": len(d["has_point"]),
                "has_trend_data": equip_has_trend.get(eq_id, False),
            }
        )
    write_csv(OUT_DIR / "equipment_nodes.csv", equip_rows)

    # -------------------------------------------------------------------------
    # 3. spatial_nodes.csv (38 rows: 1 Building + 3 Floors + 34 REC Rooms)
    # -------------------------------------------------------------------------
    spatial_rows: List[Dict[str, Any]] = [
        {
            "space_id": "bldg:building",
            "space_type": "rec:Building",
            "label": "ACME Emerald Crest HQ",
            "parent_space_id": "",
            "dbid": "DBID:1:1",
            "geographic_path": "/trees/geographic",
            "sla_criticality_tier": "Tier-1 Mission Critical",
            "weekday_daytime_occupancy_pct": 32.0,
            "comfort_pct_within_1f": 99.0,
            "served_by_equipment_ids": "bldg:area_ec_ahu_1;bldg:area_ec_ahu_2",
        },
        {
            "space_id": "bldg:ec_1st_floor",
            "space_type": "rec:Floor",
            "label": "1st Floor",
            "parent_space_id": "bldg:building",
            "dbid": "DBID:1:30555",
            "geographic_path": "/trees/geographic/#ec_1st_floor",
            "sla_criticality_tier": "Tier-1 Mission Critical",
            "weekday_daytime_occupancy_pct": 42.5,
            "comfort_pct_within_1f": 99.0,
            "served_by_equipment_ids": "bldg:area_ec_ahu_1",
        },
        {
            "space_id": "bldg:ec_2nd_floor",
            "space_type": "rec:Floor",
            "label": "2nd Floor",
            "parent_space_id": "bldg:building",
            "dbid": "DBID:1:543820",
            "geographic_path": "/trees/geographic/#ec_2nd_floor",
            "sla_criticality_tier": "Tier-2 Customer Facing",
            "weekday_daytime_occupancy_pct": 28.4,
            "comfort_pct_within_1f": 98.5,
            "served_by_equipment_ids": "bldg:area_ec_ahu_2",
        },
        {
            "space_id": "bldg:area",
            "space_type": "rec:Floor",
            "label": "Roof",
            "parent_space_id": "bldg:building",
            "dbid": "DBID:1:870195",
            "geographic_path": "/trees/geographic/#area",
            "sla_criticality_tier": "Tier-1 Mission Critical",
            "weekday_daytime_occupancy_pct": 0.0,
            "comfort_pct_within_1f": 100.0,
            "served_by_equipment_ids": "bldg:area_ec_ahu_1;bldg:area_ec_ahu_2",
        },
    ]

    for idx, (r_id, r_name, fl_id, sla_tier, occ_pct, comf_pct) in enumerate(ROOM_CATALOG, start=1):
        eq_list = room_to_equip_list.get(r_id, [])
        spatial_rows.append(
            {
                "space_id": r_id,
                "space_type": "rec:Room",
                "label": r_name,
                "parent_space_id": fl_id,
                "dbid": f"DBID:ROOM:{1000 + idx}",
                "geographic_path": f"/trees/geographic/{fl_id.split(':')[1]}/{r_id.split(':')[1]}",
                "sla_criticality_tier": sla_tier,
                "weekday_daytime_occupancy_pct": occ_pct,
                "comfort_pct_within_1f": comf_pct,
                "served_by_equipment_ids": ";".join(eq_list),
            }
        )
    write_csv(OUT_DIR / "spatial_nodes.csv", spatial_rows)

    # -------------------------------------------------------------------------
    # 4. network_and_controller_nodes.csv (100 rows: 7 Networks + 3 Inferred Hubs + 90 Controllers)
    # -------------------------------------------------------------------------
    net_ctrl_rows: List[Dict[str, Any]] = []
    # Add 7 BACnet Networks
    for net_id in sorted(net_raw.keys()):
        nd = net_raw[net_id]
        net_ctrl_rows.append(
            {
                "node_id": net_id,
                "entity_category": "bsm:Network",
                "label": nd["label"],
                "controller_model": "",
                "device_type": "network_segment",
                "media_type": nd["media_type"],
                "network_id": net_id,
                "network_number": nd["network_number"],
                "physical_shape": nd["physical_shape"],
                "mac_address": "",
                "ip_address": "172.31.222.64/26" if net_id == "bldg:network_888" else "",
                "subnet_mask": "255.255.255.192" if net_id == "bldg:network_888" else "",
                "default_gateway": "172.31.222.65" if net_id == "bldg:network_888" else "",
                "serial_number": "",
                "dbid": "",
                "is_router": False,
                "routes_to_Or_behind_router": nd["behind_router"][0] if nd["behind_router"] else "",
                "config_anomaly_flag": "NONE",
            }
        )

    # Add 3 Inferred Network Devices (from network_topology.html & TTL)
    inferred_devices = [
        (
            "bldg:network_2401_hub",
            "SC Hub (Inferred net 2401)",
            "BACnet/SC",
            "bldg:network_2401",
            "2401",
            "star",
            "",
            "",
            "",
            "NONE",
        ),
        (
            "bldg:network_888_hub",
            "Ethernet Switch (Inferred net 888)",
            "BACnet/IP",
            "bldg:network_888",
            "888",
            "star",
            "172.31.222.64/26",
            "255.255.255.192",
            "172.31.222.65",
            "NONE",
        ),
        (
            "bldg:gateway_172_31_222_65",
            "Default Gateway 172.31.222.65 (NAT 172.31.239.22)",
            "BACnet/IP",
            "bldg:network_888",
            "888",
            "star",
            "172.31.222.65",
            "255.255.255.192",
            "172.31.239.22",
            "NONE",
        ),
    ]
    for inf_id, inf_lbl, med, n_id, n_num, shape, ip_a, mask, gw, flag in inferred_devices:
        net_ctrl_rows.append(
            {
                "node_id": inf_id,
                "entity_category": "bsm:InferredNetworkDevice",
                "label": inf_lbl,
                "controller_model": "Inferred-Switch-Gateway",
                "device_type": "inferred_network_infrastructure",
                "media_type": med,
                "network_id": n_id,
                "network_number": n_num,
                "physical_shape": shape,
                "mac_address": "",
                "ip_address": ip_a,
                "subnet_mask": mask,
                "default_gateway": gw,
                "serial_number": "",
                "dbid": "",
                "is_router": True if "gateway" in inf_id else False,
                "routes_to_Or_behind_router": n_id,
                "config_anomaly_flag": flag,
            }
        )

    # Add all 64 explicit BACnet devices/controllers from ctrl_raw + 26 brick:Controller entities to reach 90 Controllers (100 total network/controller rows)
    for c_id in sorted(ctrl_raw.keys()):
        if c_id in ("bldg:network_2401_hub", "bldg:network_888_hub", "bldg:gateway_172_31_222_65"):
            continue
        cd = ctrl_raw[c_id]
        is_rtr = "bsm:Router" in cd["rdf_types"] or bool(cd["routes_to"])
        anomaly = (
            "SUBNET_MASK_MISMATCH_255.255.255.0_VS_/26"
            if c_id == "bldg:bacnet_device_71101"
            else ("MSTP_102_HIGH_RETRY_BOTTLENECK" if c_id == "bldg:bacnet_device_301002" else "NONE")
        )
        net_ctrl_rows.append(
            {
                "node_id": c_id,
                "entity_category": "bsm:Router" if is_rtr else "bsm:Controller",
                "label": cd["controller_name"] or cd["label"],
                "controller_model": cd["controller_model"] or "BACnet-Std",
                "device_type": cd["device_type"] or "bacnet_device",
                "media_type": cd["media_type"] or "bacnet/ip",
                "network_id": cd["on_network"][0] if cd["on_network"] else "bldg:network_888",
                "network_number": cd["network_number"] or "888",
                "physical_shape": "bus" if cd["media_type"] in ("ms/tp", "arcnet") else "star",
                "mac_address": cd["mac_address"],
                "ip_address": cd["ip_address"],
                "subnet_mask": cd["subnet_mask"],
                "default_gateway": cd["default_gateway"],
                "serial_number": cd["serial_number"],
                "dbid": cd["dbid"],
                "is_router": is_rtr,
                "routes_to_Or_behind_router": cd["routes_to"][0] if cd["routes_to"] else "",
                "config_anomaly_flag": anomaly,
            }
        )

    # Add sub-controllers classified as brick:Controller inside equip_raw + shared router sub-programs so total = 100 rows
    brick_ctrls = [
        (eq_id, eq_d)
        for eq_id, eq_d in sorted(equip_raw.items())
        if "brick:Controller" in eq_d["rdf_types"] or eq_d["controller"] == ["bldg:bacnet_device_301002"]
    ]
    for eq_id, eq_d in brick_ctrls:
        if len(net_ctrl_rows) >= 100:
            break
        parent_ctrl = eq_d["controller"][0] if eq_d["controller"] else "bldg:bacnet_device_260000"
        parent_net = (
            ctrl_raw[parent_ctrl]["on_network"][0]
            if parent_ctrl in ctrl_raw and ctrl_raw[parent_ctrl]["on_network"]
            else "bldg:network_888"
        )
        net_ctrl_rows.append(
            {
                "node_id": f"{eq_id}_ctrl_logical",
                "entity_category": "bsm:Controller",
                "label": f"Logical Controller: {eq_d['label']}",
                "controller_model": "IAQVent-SubController",
                "device_type": "logical_controller",
                "media_type": "bacnet/ip",
                "network_id": parent_net,
                "network_number": "888",
                "physical_shape": "star",
                "mac_address": "",
                "ip_address": "",
                "subnet_mask": "",
                "default_gateway": "",
                "serial_number": "",
                "dbid": eq_d["dbid"],
                "is_router": False,
                "routes_to_Or_behind_router": parent_ctrl,
                "config_anomaly_flag": "NONE",
            }
        )
    write_csv(OUT_DIR / "network_and_controller_nodes.csv", net_ctrl_rows)

    # -------------------------------------------------------------------------
    # 5. Unified Property Graph Tables: graph_nodes.csv (250 rows) & graph_edges.csv (410+ rows)
    # -------------------------------------------------------------------------
    print("[4/7] Generating unified BigQuery Property Graph tables: graph_nodes.csv & graph_edges.csv ...")
    graph_nodes: List[Dict[str, Any]] = []
    # 38 Spatial Nodes (1 Building + 3 Floors + 34 Rooms)
    for sp in spatial_rows:
        graph_nodes.append(
            {
                "node_id": sp["space_id"],
                "node_category": "Space",
                "ontology_class": sp["space_type"],
                "label": sp["label"],
                "dbid": sp["dbid"],
                "floor_id": sp["parent_space_id"] or sp["space_id"],
                "network_id": "",
                "sla_tier": sp["sla_criticality_tier"],
                "metadata_json": json.dumps(
                    {
                        "daytime_occupancy_pct": sp["weekday_daytime_occupancy_pct"],
                        "comfort_pct": sp["comfort_pct_within_1f"],
                    }
                ),
            }
        )
    # 122 primary Equipment Nodes (or all 126 equipment nodes; let's include all 126 equipment + 7 networks + 3 inferred + 76 physical controllers = 250 nodes!)
    for eq in equip_rows[:122]:
        graph_nodes.append(
            {
                "node_id": eq["node_id"],
                "node_category": "Equipment",
                "ontology_class": eq["brick_class"],
                "label": eq["label"],
                "dbid": eq["dbid"],
                "floor_id": eq["floor_id"],
                "network_id": "",
                "sla_tier": "Tier-1 Mission Critical"
                if "server_rm" in eq["node_id"] or "ahu" in eq["node_id"]
                else "Tier-3 Standard",
                "metadata_json": json.dumps(
                    {
                        "ashrae_223p": eq["ashrae_223p_class"],
                        "template": eq["template"],
                        "program": eq["program_name"],
                        "confidence": eq["class_confidence"],
                    }
                ),
            }
        )
    for nc in net_ctrl_rows[:90]:
        graph_nodes.append(
            {
                "node_id": nc["node_id"],
                "node_category": "Network" if nc["entity_category"] == "bsm:Network" else "Controller",
                "ontology_class": nc["entity_category"],
                "label": nc["label"],
                "dbid": nc["dbid"],
                "floor_id": "",
                "network_id": nc["network_id"],
                "sla_tier": "Tier-1 Network Backbone" if nc["is_router"] else "Tier-3 Field Bus",
                "metadata_json": json.dumps(
                    {
                        "model": nc["controller_model"],
                        "media_type": nc["media_type"],
                        "ip_address": nc["ip_address"],
                        "subnet_mask": nc["subnet_mask"],
                        "anomaly": nc["config_anomaly_flag"],
                    }
                ),
            }
        )
    write_csv(OUT_DIR / "graph_nodes.csv", graph_nodes)

    # Build graph_edges.csv
    graph_edges: List[Dict[str, Any]] = []
    edge_seq = 1

    def add_edge(src: str, dst: str, etype: str, pred: str, conf: str = "high") -> None:
        nonlocal edge_seq
        if not src or not dst:
            return
        graph_edges.append(
            {
                "edge_id": f"EDGE-{edge_seq:04d}",
                "source_node_id": src,
                "target_node_id": dst,
                "edge_type": etype,
                "ontology_predicate": pred,
                "confidence": conf,
            }
        )
        edge_seq += 1

    # 1) 44 FEEDS edges (AHU-1 -> 20 terminals, AHU-2 -> 24 terminals)
    for eq_id, d in sorted(equip_raw.items()):
        for fed_target in d["feeds"]:
            add_edge(eq_id, fed_target, "FEEDS", "brick:feeds", "high")

    # 2) LOCATED_IN edges (Equipment -> Room & Equipment -> Floor)
    for eq in equip_rows:
        if eq["room_id"]:
            add_edge(eq["node_id"], eq["room_id"], "LOCATED_IN", "brick:hasLocation", "medium")
        elif eq["floor_id"]:
            add_edge(eq["node_id"], eq["floor_id"], "LOCATED_IN", "brick:hasLocation", "high")

    # 3) CONTROLLED_BY edges (Equipment -> BACnet Controller)
    for eq in equip_rows:
        if eq["controller_id"]:
            add_edge(eq["node_id"], eq["controller_id"], "CONTROLLED_BY", "bsm:controller", "high")

    # 4) ON_NETWORK & ROUTES_TO edges (Controllers -> Networks, Routers -> Downstream Networks)
    for c_id, cd in sorted(ctrl_raw.items()):
        for net_target in cd["on_network"]:
            add_edge(c_id, net_target, "ON_NETWORK", "bsm:onNetwork", "high")
        for r_target in cd["routes_to"]:
            add_edge(c_id, r_target, "ROUTES_TO", "bsm:routesTo", "high")

    for net_id, nd in sorted(net_raw.items()):
        for rtr in nd["behind_router"]:
            add_edge(net_id, rtr, "BEHIND_ROUTER", "bsm:behindRouter", "high")

    # 5) PART_OF spatial containment edges (Room -> Floor -> Building)
    for sp in spatial_rows:
        if sp["parent_space_id"]:
            add_edge(sp["space_id"], sp["parent_space_id"], "PART_OF", "brick:isPartOf", "high")

    # 6) Logical Sub-Controller -> Parent BACnet Controller edges to reach exact 410 graph edges
    for nc in net_ctrl_rows:
        if len(graph_edges) >= 410:
            break
        if nc["device_type"] == "logical_controller" and nc["routes_to_Or_behind_router"]:
            add_edge(
                nc["node_id"],
                nc["routes_to_Or_behind_router"],
                "HOSTED_ON_CONTROLLER",
                "bsm:controller",
                "high",
            )

    write_csv(OUT_DIR / "graph_edges.csv", graph_edges)

    # -------------------------------------------------------------------------
    # 6. point_catalog.csv (1,653 rows) & svweb_datasources.csv (350 active series)
    # -------------------------------------------------------------------------
    print("[5/7] Generating point_catalog.csv (1,653 points) and svweb_datasources.csv (350 active trend series) ...")
    point_rows: List[Dict[str, Any]] = []
    datasources_rows: List[Dict[str, Any]] = []

    # First collect all 272 points that already have `ref:TimeseriesReference`
    ts_points: List[str] = []
    non_ts_candidates: List[str] = []

    for pt_id in sorted(points_raw.keys()):
        if points_raw[pt_id]["ts_ref"]:
            ts_points.append(pt_id)
        else:
            non_ts_candidates.append(pt_id)

    # Select 78 priority BACnet points to augment the 272 existing series -> 350 active series
    # Prioritize AHU-1, AHU-2, ISS Server Room, 1st floor PIU/VAVs, and 2nd floor PIUs
    def candidate_priority(pt_id: str) -> Tuple[int, str]:
        p_cls = points_raw[pt_id]["rdf_types"][0] if points_raw[pt_id]["rdf_types"] else ""
        if "area_ec_ahu_1" in pt_id or "area_ec_ahu_2" in pt_id or "ec_server_rm" in pt_id:
            return (0, pt_id)
        if any(
            k in p_cls
            for k in (
                "Temperature_Sensor",
                "Temperature_Setpoint",
                "Air_Flow",
                "Fan_Command",
                "Stage_Enable",
                "Electric_Power",
                "Override_Command",
                "Occupancy",
            )
        ):
            return (1, pt_id)
        return (2, pt_id)

    non_ts_candidates.sort(key=candidate_priority)
    augmented_78 = set(non_ts_candidates[: (350 - len(ts_points))])
    active_350_set = set(ts_points) | augmented_78

    synthetic_tid_counter = 5001
    for pt_id in sorted(points_raw.keys()):
        pd = points_raw[pt_id]
        eq_id = point_to_equip.get(pt_id, pt_id.split("__")[0])
        brick_cls = pd["rdf_types"][0] if pd["rdf_types"] else "brick:Point"
        ts_info = pd["ts_ref"]
        bac_info = pd["bac_ref"]
        is_active = pt_id in active_350_set

        if ts_info:
            tid = ts_info.get("timeseries_id", "")
            s_table = ts_info.get("series_table", f"DATASERIES_{tid}")
            m_basis = ts_info.get("match_basis", "exact_name_match")
            m_status = ts_info.get("match_status", "auto")
        elif is_active:
            tid = str(synthetic_tid_counter)
            synthetic_tid_counter += 1
            s_table = f"DATASERIES_{tid}"
            m_basis = "augmented_bacnet_telemetry_binding"
            m_status = "synthetic_active"
        else:
            tid = ""
            s_table = ""
            m_basis = ""
            m_status = "untrended"

        # Determine Golden Scenario association
        scenario_tag = "BASELINE"
        if eq_id == "bldg:area_ec_ahu_1" or (
            eq_id in serving_ahu_map and serving_ahu_map[eq_id] == "bldg:area_ec_ahu_1"
        ):
            scenario_tag = "SCN-1_AHU1_COOLING_FAULT"
        if eq_id in equip_raw and equip_raw[eq_id]["controller"]:
            c_id = equip_raw[eq_id]["controller"][0]
            if c_id in ctrl_raw and ctrl_raw[c_id]["network_number"] == "102":
                scenario_tag = "SCN-2_MSTP102_BUS_BOTTLENECK"
        if "emrd_2_piu_1" in eq_id or "emrd_2_piu_20" in eq_id or "2nd_floor" in eq_id or "irrigation" in eq_id:
            if scenario_tag == "BASELINE":
                scenario_tag = "SCN-3_SILENT_ENERGY_BLEED"
        if "ec_server_rm" in eq_id:
            scenario_tag = "SCN-4_CRITICAL_SERVER_ROOM_SLA"

        point_rows.append(
            {
                "point_id": pt_id,
                "equipment_id": eq_id,
                "brick_class": brick_cls,
                "label": pd["label"],
                "unit": pd["unit"],
                "point_ref": pd["point_ref"],
                "bacnet_block": pd["bacnet_block"],
                "class_rule": pd["class_rule"],
                "class_confidence": pd["class_confidence"] or "high",
                "bacnet_uri": bac_info.get("bacnet_uri", ""),
                "bacnet_object_type": bac_info.get("object_type", ""),
                "bacnet_object_id": bac_info.get("object_identifier", ""),
                "bacnet_device_id": bac_info.get("object_of", ""),
                "has_timeseries": bool(ts_info) or is_active,
                "timeseries_id": tid,
                "series_table": s_table,
                "is_active_350_demo_series": is_active,
                "match_basis": m_basis,
                "match_status": m_status,
                "historical_record_count": 2688 if is_active else int(ts_info.get("record_count", 0) or 0),
                "oldest_sample": "2026-09-09 00:00:00.0" if is_active else ts_info.get("oldest_sample", ""),
                "newest_sample": "2026-10-07 09:30:00.0" if is_active else ts_info.get("newest_sample", ""),
                "golden_scenario_id": scenario_tag,
            }
        )

        if is_active:
            datasources_rows.append(
                {
                    "tid": tid,
                    "series_table": f"SVWEB.{s_table}",
                    "point_id": pt_id,
                    "equipment_id": eq_id,
                    "brick_class": brick_cls,
                    "unit": pd["unit"] or "unit:UNITLESS",
                    "sampling_interval_minutes": 15,
                    "sample_count": 2688,
                    "oldest_sample": "2026-09-09 00:00:00",
                    "newest_sample": "2026-10-07 09:30:00",
                    "match_status": m_status,
                    "golden_scenario_id": scenario_tag,
                }
            )

    write_csv(OUT_DIR / "point_catalog.csv", point_rows)
    write_csv(OUT_DIR / "svweb_datasources.csv", datasources_rows)

    # -------------------------------------------------------------------------
    # 7. telemetry_ts.csv (940,800 rows: 350 series x 2,688 15-min timestamps)
    # -------------------------------------------------------------------------
    print("[6/7] Generating telemetry_ts.csv (940,800 rows across 350 series x 2,688 15-min intervals) ...")
    # 2,688 intervals of 15 minutes ending at 2026-10-07 09:30:00
    end_dt = datetime.datetime(2026, 10, 7, 9, 30, 0)
    num_steps = 2688
    start_dt = end_dt - datetime.timedelta(minutes=15 * (num_steps - 1))
    timestamps = [
        (start_dt + datetime.timedelta(minutes=15 * i)).strftime("%Y-%m-%d %H:%M:%S")
        for i in range(num_steps)
    ]
    hours = [(start_dt + datetime.timedelta(minutes=15 * i)).hour for i in range(num_steps)]
    weekdays = [(start_dt + datetime.timedelta(minutes=15 * i)).weekday() for i in range(num_steps)]
    is_daytime = [(w < 5 and 6 <= h < 18) for w, h in zip(weekdays, hours)]
    # Diurnal sine wave (-1 at 04:00, +1 at 15:00)
    diurnal_wave = [math.sin(2.0 * math.pi * (h - 9) / 24.0) for h in hours]

    telemetry_path = OUT_DIR / "telemetry_ts.csv"
    sample_24h_path = OUT_DIR / "telemetry_ts_last_24h_sample.csv"

    total_telemetry_rows = 0
    with telemetry_path.open("w", newline="", encoding="utf-8") as f_all, sample_24h_path.open(
        "w", newline="", encoding="utf-8"
    ) as f_24h:
        fieldnames = [
            "series_table",
            "point_id",
            "equipment_id",
            "timestamp",
            "value",
            "unit",
            "quality_flag",
            "scenario_tag",
        ]
        writer_all = csv.DictWriter(f_all, fieldnames=fieldnames)
        writer_24h = csv.DictWriter(f_24h, fieldnames=fieldnames)
        writer_all.writeheader()
        writer_24h.writeheader()

        for s_idx, ds in enumerate(datasources_rows):
            s_table = ds["series_table"].replace("SVWEB.", "")
            pt_id = ds["point_id"]
            eq_id = ds["equipment_id"]
            b_cls = ds["brick_class"]
            unit_str = ds["unit"].replace("unit:", "") or "UNITLESS"
            scen = ds["golden_scenario_id"]

            # Seed per series for reproducible physics
            rng = random.Random(10000 + s_idx)

            for step in range(num_steps):
                ts_str = timestamps[step]
                day_flag = is_daytime[step]
                wave = diurnal_wave[step]
                in_last_4h = step >= (num_steps - 16)  # Final 4 hours (16 x 15-min)
                in_last_24h = step >= (num_steps - 96)
                q_flag = "OK"
                row_scen = "NORMAL"

                # Determine realistic value based on Brick point class & Golden Scenarios
                if "Supply_Air_Temperature_Sensor" in b_cls or "Discharge_Air_Temperature_Sensor" in b_cls or pt_id.endswith("__sat"):
                    val = 55.0 + 0.4 * wave + rng.uniform(-0.25, 0.25)
                    if eq_id == "bldg:area_ec_ahu_1" and in_last_4h:
                        # SCN-1: AHU-1 Stage-1 DX trip -> SAT ramps from 55.0F to 68.5F
                        progress = (step - (num_steps - 16)) / 15.0
                        val = 55.0 + 13.5 * progress + rng.uniform(-0.15, 0.15)
                        q_flag = "ANOMALY_HIGH_SAT"
                        row_scen = "SCN-1"
                    elif serving_ahu_map.get(eq_id) == "bldg:area_ec_ahu_1" and in_last_4h:
                        progress = (step - (num_steps - 16)) / 15.0
                        val = 56.5 + 11.8 * progress + rng.uniform(-0.2, 0.2)
                        q_flag = "ANOMALY_DOWNSTREAM_STARVATION"
                        row_scen = "SCN-1"

                elif "Cooling_Temperature_Setpoint" in b_cls or pt_id.endswith("sa_temp_stpt"):
                    if "sa_temp_stpt" in pt_id:
                        val = 55.0
                    else:
                        # No night setback on 2nd floor (held at 72.5F day & night)
                        val = 72.5 if day_flag else 72.5

                elif "Heating_Temperature_Setpoint" in b_cls:
                    val = 70.0 if day_flag else 70.0

                elif "Zone_Air_Temperature_Sensor" in b_cls or "Air_Temperature_Sensor" in b_cls:
                    if "oa_temp" in pt_id or "Outside" in b_cls:
                        val = 68.0 + 10.5 * wave + rng.uniform(-0.8, 0.8)
                    elif "ec_server_rm" in eq_id:
                        # SCN-4: Server Room creeping from 70.2F to 72.0F in last 24h
                        base_t = 70.2 + rng.uniform(-0.15, 0.15)
                        if in_last_24h:
                            prog_24 = (step - (num_steps - 96)) / 95.0
                            val = base_t + 1.8 * prog_24
                            q_flag = "ANOMALY_THERMAL_CREEP_SLA_TIER1"
                            row_scen = "SCN-4"
                        else:
                            val = base_t
                    elif "piu_5_1" in eq_id:
                        # PIU 5 (7-11) has 88% comfort compliance
                        val = (72.1 if day_flag else 72.3) + (1.45 if step % 8 == 0 else 0.25 * wave) + rng.uniform(-0.2, 0.2)
                    else:
                        # Matches floor_view.html: 72.0F daytime mean, 72.2F nighttime mean (no night setback!)
                        val = (72.0 + 0.35 * wave + rng.uniform(-0.25, 0.25)) if day_flag else (72.2 + 0.65 * wave + rng.uniform(-0.45, 0.45))

                    # SCN-1 impact on 1st-floor terminals fed by AHU-1 in final 4 hours
                    if serving_ahu_map.get(eq_id) == "bldg:area_ec_ahu_1" and in_last_4h:
                        progress = (step - (num_steps - 16)) / 15.0
                        val = 72.2 + 4.8 * progress + rng.uniform(-0.15, 0.25)
                        q_flag = "ALARM_HIGH_ZONE_TEMP"
                        row_scen = "SCN-1"

                elif "Occupancy" in b_cls:
                    # Matches floor_view.html: 0.32 weekday daytime mean, 0.02 nighttime mean, 7% night detections
                    if day_flag:
                        val = float(rng.choices([0, 1, 2, 3, 4], weights=[79, 10, 6, 3, 2])[0])
                    else:
                        val = 1.0 if rng.random() < 0.018 else 0.0
                        if val > 0:
                            row_scen = "SCN-3"

                elif "Air_Flow_Sensor" in b_cls:
                    if "emrd_2_piu_8" in eq_id:
                        # Matches floor_view.html: PIU 2-8 Open Office 232 has 394 cfm night vs 183 cfm day
                        val = (183.0 if day_flag else 394.0) + rng.uniform(-12.0, 12.0)
                        if not day_flag:
                            q_flag = "ANOMALY_NIGHT_OVERFLOW"
                            row_scen = "SCN-3"
                    elif "emrd_2_piu_4" in eq_id:
                        val = (210.0 if day_flag else 75.0) + rng.uniform(-8.0, 8.0)
                    else:
                        val = (340.0 if day_flag else 125.0) + 45.0 * wave + rng.uniform(-10.0, 10.0)
                    if serving_ahu_map.get(eq_id) == "bldg:area_ec_ahu_1" and in_last_4h:
                        val = val * 0.58
                        q_flag = "ALARM_AIRFLOW_STARVATION"
                        row_scen = "SCN-1"

                elif "Fan_Command" in b_cls or "Stage_Enable_Command" in b_cls or "Enable_Command" in b_cls:
                    if "ec_server_rm" in eq_id:
                        # ISS Server Room: Fan 100% day/night, heat/cool stage cycling
                        if in_last_24h and "Stage" in b_cls:
                            val = 1.0 if (step % 2 == 0) else 0.0
                            q_flag = "ANOMALY_SHORT_CYCLING_3.5X"
                            row_scen = "SCN-4"
                        else:
                            val = 1.0
                    elif "emrd_2_piu_2" in eq_id:
                        # PIU 2-2 Open Seating 228: 24% day / 34% night
                        val = 1.0 if rng.random() < (0.24 if day_flag else 0.34) else 0.0
                        if not day_flag and val > 0:
                            row_scen = "SCN-3"
                    else:
                        val = 1.0 if rng.random() < (0.68 if day_flag else 0.37) else 0.0

                elif "Electric_Power_Sensor" in b_cls or "Energy" in b_cls or "Demand_Sensor" in b_cls:
                    if "emrd_2_piu_1" in eq_id or "emrd_2_piu_3" in eq_id:
                        # PIU 2-1 Huddle / PIU 2-3 rogue reheat: 42 kWh cumulative outlier
                        val = 1.65 + 0.35 * abs(wave) + rng.uniform(-0.08, 0.08)
                        q_flag = "ANOMALY_ROGUE_REHEAT_42KWH"
                        row_scen = "SCN-3"
                    elif "emrd_2_piu_20" in eq_id:
                        # PIU 2-20 Open Office 201A: 26 kWh cumulative outlier
                        val = 1.05 + 0.25 * abs(wave) + rng.uniform(-0.06, 0.06)
                        q_flag = "ANOMALY_ROGUE_REHEAT_26KWH"
                        row_scen = "SCN-3"
                    else:
                        val = (0.45 if day_flag else 0.18) + rng.uniform(-0.04, 0.04)

                elif "CO2_Level_Sensor" in b_cls:
                    val = (580.0 if day_flag else 425.0) + 95.0 * max(0.0, wave) + rng.uniform(-15.0, 15.0)

                elif "Water_Usage_Sensor" in b_cls:
                    val = (14.5 if day_flag else 1.2) + rng.uniform(-0.4, 0.4)

                elif "Override_Command" in b_cls:
                    # 24 manual override events on 12 irrigation/HVAC points, max 30 min (2 steps)
                    if step in (420, 421, 1180, 1181):
                        val = 30.0
                        q_flag = "MANUAL_OVERRIDE_ACTIVE"
                        row_scen = "SCN-3"
                    else:
                        val = 0.0

                else:
                    val = 50.0 + 10.0 * wave + rng.uniform(-1.5, 1.5)

                # SCN-2: MSTP-102 bus bottleneck in last 4 hours -> stale telemetry / packet error flag
                if scen == "SCN-2_MSTP102_BUS_BOTTLENECK" and in_last_4h:
                    q_flag = "STALE_TELEMETRY_MSTP102_42PCT_LOSS"
                    row_scen = "SCN-2"

                row_dict = {
                    "series_table": s_table,
                    "point_id": pt_id,
                    "equipment_id": eq_id,
                    "timestamp": ts_str,
                    "value": round(val, 2),
                    "unit": unit_str,
                    "quality_flag": q_flag,
                    "scenario_tag": row_scen,
                }
                writer_all.writerow(row_dict)
                if in_last_24h and s_idx < 40:
                    writer_24h.writerow(row_dict)
                total_telemetry_rows += 1

    # -------------------------------------------------------------------------
    # 8. bas_events.csv (360 rows: 322 historical + 38 active Golden Scenario alarms)
    # -------------------------------------------------------------------------
    print("[7/7] Generating bas_events.csv (360 rows: 322 historical + 38 active Golden Scenario alarms) ...")
    bas_events: List[Dict[str, Any]] = []
    ev_seq = 1

    def add_event(
        ts: str,
        eq_id: str,
        ctrl_id: str,
        net_id: str,
        ev_type: str,
        sev: str,
        status: str,
        scen_id: str,
        msg: str,
    ) -> None:
        nonlocal ev_seq
        bas_events.append(
            {
                "event_id": f"ALM-{ev_seq:04d}",
                "timestamp": ts,
                "equipment_id": eq_id,
                "controller_id": ctrl_id,
                "network_id": net_id,
                "event_category": ev_type,
                "severity": sev,
                "status": status,
                "golden_scenario_id": scen_id,
                "message": msg,
            }
        )
        ev_seq += 1

    # 1) Historical Trail Guide alarms matching exact screenshot counts:
    #    - PIU 5 (7-11) (`bldg:ec_1st_floor_piu_5_1`): 44 alarms (43 historical + 1 active in SCN-1)
    #    - PIU 10 (NSA Offices) (`bldg:ec_1st_floor_piu_10_1`): 41 alarms (40 historical + 1 active in SCN-1)
    #    - PIU 1 (NSA Office) (`bldg:ec_1st_floor_piu_1_1`): 8 alarms (7 historical + 1 active in SCN-1)
    for i in range(43):
        dt_h = (start_dt + datetime.timedelta(hours=14 * i + 3)).strftime("%Y-%m-%d %H:%M:%S")
        add_event(
            dt_h,
            "bldg:ec_1st_floor_piu_5_1",
            "bldg:bacnet_device_301002",
            "bldg:network_102",
            "ZONE_TEMP_DEVIATION",
            "WARNING",
            "HISTORICAL_CLEARED",
            "HISTORICAL_TRAIL_GUIDE",
            "PIU 5 (7-11): Zone temperature exceeded occupied comfort band (+/- 1.0 F) — Trail Guide Log (#1..44)",
        )

    for i in range(40):
        dt_h = (start_dt + datetime.timedelta(hours=15 * i + 5)).strftime("%Y-%m-%d %H:%M:%S")
        add_event(
            dt_h,
            "bldg:ec_1st_floor_piu_10_1",
            "bldg:bacnet_device_301002",
            "bldg:network_102",
            "ZONE_TEMP_DEVIATION",
            "WARNING",
            "HISTORICAL_CLEARED",
            "HISTORICAL_TRAIL_GUIDE",
            "PIU 10 (NSA Offices): Zone temperature drift & airflow hunting — Trail Guide Log (#1..41)",
        )

    for i in range(7):
        dt_h = (start_dt + datetime.timedelta(days=3 * i + 2, hours=10)).strftime("%Y-%m-%d %H:%M:%S")
        add_event(
            dt_h,
            "bldg:ec_1st_floor_piu_1_1",
            "bldg:bacnet_device_301002",
            "bldg:network_102",
            "PROGRAM_DOWNLOAD_REQUIRED" if i == 6 else "ZONE_TEMP_DEVIATION",
            "WARNING",
            "HISTORICAL_CLEARED",
            "HISTORICAL_TRAIL_GUIDE",
            "PIU 1 (NSA Office): The controller's programming has changed. Please download all content to update programs in the controller."
            if i == 6
            else "PIU 1 (NSA Office): Zone comfort deviation — Trail Guide Log (#1..8)",
        )

    # 2) 24 Manual Override events on 12 irrigation/HVAC points (matching floor_view.html: 235 min total, max 30 min)
    for i in range(24):
        valve_num = (i % 12) + 1
        dt_h = (start_dt + datetime.timedelta(days=i, hours=11, minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        dur_min = 30 if i == 0 else random.choice([5, 10, 10, 15])
        add_event(
            dt_h,
            "bldg:alcs_development_area_irrigation_valve_control_ec",
            "bldg:bacnet_device_301005",
            "bldg:network_4401",
            "MANUAL_OPERATOR_OVERRIDE",
            "INFO",
            "HISTORICAL_CLEARED",
            "SCN-3_SILENT_ENERGY_BLEED",
            f"Operator manual override on vlvovr_{valve_num} (duration {dur_min} min; cumulative 235 min across 24 override events)",
        )

    # 3) Fill remaining historical background events (208 events) to reach 322 historical events
    hist_equip_pool = [
        ("bldg:ec_1st_floor_vav_4_1", "bldg:bacnet_device_301002", "bldg:network_102", "VAV 4 (NSA Cubes) damper actuator hunting"),
        ("bldg:ec_1st_floor_piu_6_1", "bldg:bacnet_device_301002", "bldg:network_102", "PIU 6 (7-11) discharge air temperature transient"),
        ("bldg:ec_2nd_floor_area8_emrd_2_piu_2", "bldg:bacnet_device_3010002", "bldg:network_30100", "PIU 2-2 Open Seating 228 after-hours fan runtime"),
        ("bldg:ec_2nd_floor_area8_emrd_2_piu_8", "bldg:bacnet_device_3010008", "bldg:network_30100", "PIU 2-8 Open Office 232 night airflow 394 cfm > daytime 183 cfm"),
        ("bldg:area_ec_ahu_2", "bldg:bacnet_device_301003", "bldg:network_3011", "RTU-2 economizer outdoor air enthalpy switchover"),
    ]
    while len(bas_events) < 322:
        idx = len(bas_events)
        eq_h, ctrl_h, net_h, desc_h = hist_equip_pool[idx % len(hist_equip_pool)]
        dt_h = (start_dt + datetime.timedelta(minutes=115 * idx)).strftime("%Y-%m-%d %H:%M:%S")
        add_event(
            dt_h,
            eq_h,
            ctrl_h,
            net_h,
            "ROUTINE_BAS_NOTIFICATION",
            "LOW",
            "HISTORICAL_CLEARED",
            "HISTORICAL_BASELINE",
            desc_h,
        )

    # -------------------------------------------------------------------------
    # 4) 38 ACTIVE ALARMS IN CURRENT 4-HOUR WINDOW (Collapsing into 4 Golden Scenarios)
    # -------------------------------------------------------------------------
    # Golden Scenario 1 (15 Active Alarms): 1 Rooftop AHU-1 fault + 14 downstream 1st-floor PIU/VAV comfort/starvation alarms
    add_event(
        "2026-10-07 06:15:00",
        "bldg:area_ec_ahu_1",
        "bldg:bacnet_device_301003",
        "bldg:network_3011",
        "MECHANICAL_COOLING_STAGE_FAULT",
        "CRITICAL",
        "ACTIVE_UNACKNOWLEDGED",
        "SCN-1_AHU1_COOLING_FAULT",
        "RTU-1 (ACME) BACnet Integration to UPC [DBID:1:856800]: Supply Air Temp drifted to 68.5 F vs 55.0 F setpoint (Stage-1 DX Compressor Trip)",
    )
    scn1_terminals = [
        ("bldg:ec_1st_floor_piu_1_1", "PIU 1 (NSA Office)"),
        ("bldg:ec_1st_floor_piu_2_1", "PIU 2 (Lobby)"),
        ("bldg:ec_1st_floor_piu_3_1", "PIU 3 (OEM)"),
        ("bldg:ec_1st_floor_piu_4_1", "PIU 4 (OEM)"),
        ("bldg:ec_1st_floor_piu_5_1", "PIU 5 (7-11) [Alarm #44]"),
        ("bldg:ec_1st_floor_piu_6_1", "PIU 6 (7-11)"),
        ("bldg:ec_1st_floor_piu_7_1", "PIU 7 (NSA Cubes)"),
        ("bldg:ec_1st_floor_piu_8_1", "PIU 8 (Break Room)"),
        ("bldg:ec_1st_floor_piu_9_1", "PIU 9 (NSA Cubes)"),
        ("bldg:ec_1st_floor_piu_10_1", "PIU 10 (NSA Offices) [Alarm #41]"),
        ("bldg:ec_1st_floor_vav_1_1", "VAV 1 (ALCS/TPI)"),
        ("bldg:ec_1st_floor_vav_2_1", "VAV 2 (NSA Copier)"),
        ("bldg:ec_1st_floor_vav_4_1", "VAV 4 (NSA Cubes)"),
        ("bldg:ec_1st_floor_vav_5_1", "VAV 5 (NSA)"),
    ]
    for t_idx, (t_id, t_lbl) in enumerate(scn1_terminals):
        add_event(
            f"2026-10-07 07:{10 + t_idx * 2:02d}:00",
            t_id,
            "bldg:bacnet_device_301002",
            "bldg:network_102",
            "DOWNSTREAM_ZONE_TEMP_HIGH",
            "HIGH",
            "ACTIVE_UNACKNOWLEDGED",
            "SCN-1_AHU1_COOLING_FAULT",
            f"{t_lbl}: Zone temperature > 76.2 F and primary damper saturated at 100% (Upstream AHU-1 thermal starvation)",
        )

    # Golden Scenario 2 (17 Active Alarms): 1 Subnet Mismatch / Router Bottleneck + 16 MS/TP-102 Controller Timeout Alarms
    add_event(
        "2026-10-07 08:05:00",
        "bldg:1st_floor_lighitng",
        "bldg:bacnet_device_71101",
        "bldg:network_888",
        "BACNET_IP_SUBNET_MISMATCH",
        "HIGH",
        "ACTIVE_UNACKNOWLEDGED",
        "SCN-2_MSTP102_BUS_BOTTLENECK",
        "MES eBox - Showcase (#71101 on IP 172.31.222.99): Subnet mask 255.255.255.0 conflicts with /26 (255.255.255.192) on BACnet/IP net 888, causing BBMD broadcast retries",
    )
    mstp_controllers = [
        (c_id, ctrl_raw[c_id]["controller_name"] or c_id)
        for c_id, cd in sorted(ctrl_raw.items())
        if cd["network_number"] == "102" or c_id == "bldg:bacnet_device_301002"
    ]
    # Include the remaining shared 1st-floor MS/TP terminal channels routed through #301002 so all 16 bus channels report timeouts
    for p_id, pd in sorted(prog_raw.items()):
        if len(mstp_controllers) >= 16:
            break
        if "piu_00" in p_id or "vav_00" in p_id:
            mstp_controllers.append((p_id, f"MS/TP-102 Channel {pd['label']}"))

    for m_idx, (mc_id, mc_name) in enumerate(mstp_controllers[:16]):
        add_event(
            f"2026-10-07 08:{12 + m_idx * 2:02d}:00",
            "bldg:alcs_development_area_area3011",
            mc_id,
            "bldg:network_102",
            "BACNET_MSTP_POLL_TIMEOUT",
            "HIGH",
            "ACTIVE_UNACKNOWLEDGED",
            "SCN-2_MSTP102_BUS_BOTTLENECK",
            f"{mc_name} ({mc_id}) on RS-485 bus MSTP-102 behind Router 02 AMR/UNI-32 (#301002): 42% APDU packet loss & stale Present_Value",
        )

    # Golden Scenario 3 (4 Active Soft-Alarms / Analytics Alerts): Rogue Reheat (PIU 2-1 & PIU 2-20), Missing Night Setback, Night Fan Run
    scn3_alerts = [
        (
            "bldg:ec_2nd_floor_area9_emrd_2_piu_1",
            "bldg:bacnet_device_3010001",
            "bldg:network_30100",
            "PIU 2-1 Huddle / PIU 2-3: Simultaneous heating & cooling reheat outlier (42 kWh = 54% of entire 2nd-floor reheat energy)",
        ),
        (
            "bldg:ec_2nd_floor_area7_emrd_2_piu_20",
            "bldg:bacnet_device_3010020",
            "bldg:network_30100",
            "PIU 2-20 Open Office 201A: Rogue electric reheat consumption (26 kWh despite 17% daytime room occupancy)",
        ),
        (
            "bldg:area_ec_ahu_2",
            "bldg:bacnet_device_301003",
            "bldg:network_30100",
            "2nd Floor Fleet Drift: Missing Night Setback (72.2 F night avg vs 72.0 F day avg) & 37% night fan runtime ($18,400/yr waste)",
        ),
        (
            "bldg:ec_2nd_floor_area8_emrd_2_piu_8",
            "bldg:bacnet_device_3010008",
            "bldg:network_30100",
            "PIU 2-8 Open Office 232: Nighttime airflow averaging 394 cfm vs 183 cfm daytime (unoccupied schedule inversion)",
        ),
    ]
    for s_idx, (eq_s3, ctrl_s3, net_s3, msg_s3) in enumerate(scn3_alerts):
        add_event(
            f"2026-10-07 08:{45 + s_idx * 3:02d}:00",
            eq_s3,
            ctrl_s3,
            net_s3,
            "ENERGY_DRIFT_SETBACK_ANOMALY",
            "MEDIUM",
            "ACTIVE_UNACKNOWLEDGED",
            "SCN-3_SILENT_ENERGY_BLEED",
            msg_s3,
        )

    # Golden Scenario 4 (2 Active Predictive SLA Alerts): ISS Server Room FCU short-cycling & thermal creep
    add_event(
        "2026-10-07 09:15:00",
        "bldg:ec_1st_floor_ec_server_rm",
        "bldg:bacnet_device_301101",
        "bldg:network_888",
        "PREDICTIVE_COMPRESSOR_SHORT_CYCLING",
        "CRITICAL",
        "ACTIVE_UNACKNOWLEDGED",
        "SCN-4_CRITICAL_SERVER_ROOM_SLA",
        "ISS Server Room FCU [DBID:1:856291]: Stage-1 DX Cooling cycle_count spiked 3.5x above 28-day baseline (TimesFM AI.DETECT_ANOMALIES p=0.998)",
    )
    add_event(
        "2026-10-07 09:25:00",
        "bldg:ec_1st_floor_ec_server_rm",
        "bldg:bacnet_device_301101",
        "bldg:network_888",
        "SLA_TIER1_THERMAL_DRIFT_WARNING",
        "CRITICAL",
        "ACTIVE_UNACKNOWLEDGED",
        "SCN-4_CRITICAL_SERVER_ROOM_SLA",
        "ISS Server Room [REC Tier-1 Mission Critical Space]: Zone temperature crept +1.8 F (70.2 F -> 72.0 F); projected to breach 75.0 F SLA limit within 3.5 hours",
    )

    write_csv(OUT_DIR / "bas_events.csv", bas_events)

    # Also write bas_events_baseline.csv (322 historical cleared events only, for T=0 clean demo start)
    bas_events_baseline = [ev for ev in bas_events if ev["status"] == "HISTORICAL_CLEARED"]
    write_csv(OUT_DIR / "bas_events_baseline.csv", bas_events_baseline)

    # Build live_injection_payloads.json for the Companion Admin UI (/admin tab) & FastAPI SSE simulator
    scn1_events = [ev for ev in bas_events if ev["golden_scenario_id"] == "SCN-1_AHU1_COOLING_FAULT" and ev["status"] == "ACTIVE_UNACKNOWLEDGED"]
    scn2_events = [ev for ev in bas_events if ev["golden_scenario_id"] == "SCN-2_MSTP102_BUS_BOTTLENECK" and ev["status"] == "ACTIVE_UNACKNOWLEDGED"]
    scn3_events = [ev for ev in bas_events if ev["golden_scenario_id"] == "SCN-3_SILENT_ENERGY_BLEED" and ev["status"] == "ACTIVE_UNACKNOWLEDGED"]
    scn4_events = [ev for ev in bas_events if ev["golden_scenario_id"] == "SCN-4_CRITICAL_SERVER_ROOM_SLA" and ev["status"] == "ACTIVE_UNACKNOWLEDGED"]

    live_injection_payloads = {
        "admin_console_route": "/admin",
        "sse_stream_endpoint": "/api/events/stream",
        "inject_endpoint": "POST /api/admin/inject",
        "reset_endpoint": "POST /api/admin/reset",
        "baseline_state": {
            "state_id": "CLEAN_BASELINE_T0",
            "active_raw_alarms": 0,
            "correlated_incidents": 0,
            "zone_comfort_compliance_pct": 99.6,
            "sla_status": "HEALTHY",
            "historical_events_count": len(bas_events_baseline),
        },
        "live_scenarios": {
            "OPTION_A_SCN1_CASCADING_RTU1_FAILURE": {
                "scenario_id": "SCN-1_AHU1_COOLING_FAULT",
                "button_label": "Option A — Trigger Cascading Rooftop Unit Failure (RTU-1 -> 14 1st-Floor Zones)",
                "badge": "15 Raw Alarms -> 1 Root Cause Incident (93.3% Noise Reduction)",
                "root_cause_node": "bldg:area_ec_ahu_1",
                "root_cause_dbid": "DBID:1:856800",
                "target_agent": "Triage_And_RootCause_Agent",
                "waves": [
                    {
                        "wave_index": 1,
                        "delay_seconds": 0,
                        "title": "Upstream Rooftop Unit Stage-1 DX Compressor Trip",
                        "telemetry_override": {
                            "point_id": "bldg:area_ec_ahu_1__sat",
                            "previous_value": 55.0,
                            "injected_value": 68.5,
                            "unit": "DEG_F",
                        },
                        "events": scn1_events[:1],
                        "affected_rooms": [],
                    },
                    {
                        "wave_index": 2,
                        "delay_seconds": 3,
                        "title": "Wave 1 Downstream Thermal Starvation (PIU 1 - PIU 5)",
                        "events": scn1_events[1:6],
                        "affected_rooms": [
                            "bldg:room_1f_nsa_office",
                            "bldg:room_1f_lobby",
                            "bldg:room_1f_oem",
                            "bldg:room_1f_7_11",
                        ],
                    },
                    {
                        "wave_index": 3,
                        "delay_seconds": 6,
                        "title": "Wave 2 Downstream Thermal Starvation (PIU 6 - PIU 10)",
                        "events": scn1_events[6:11],
                        "affected_rooms": [
                            "bldg:room_1f_nsa_cubes",
                            "bldg:room_1f_break_room",
                            "bldg:room_1f_nsa_offices",
                        ],
                    },
                    {
                        "wave_index": 4,
                        "delay_seconds": 9,
                        "title": "Wave 3 VAV Damper Saturation (VAV 1, VAV 2, VAV 4, VAV 5) & Autonomous ADK 2.0 Triage",
                        "events": scn1_events[11:15],
                        "affected_rooms": [
                            "bldg:room_1f_alcs_tpi",
                            "bldg:room_1f_nsa_copier",
                            "bldg:room_1f_nsa",
                        ],
                        "autonomous_agent_action": {
                            "orchestrator": "ABO_Orchestrator_Agent",
                            "subagent": "Triage_And_RootCause_Agent",
                            "gql_query_executed": "GRAPH acme_abo_telemetry.acme_building_graph MATCH (ahu:Equipment)-[:FEEDS]->(z:Equipment)-[:LOCATED_IN]->(r:Space) WHERE ahu.node_id = 'bldg:area_ec_ahu_1'",
                            "collapsed_incident_title": "INC-1001: Rooftop AHU-1 Stage-1 DX Cooling Trip Starving 14 1st-Floor Zones",
                            "hitl_remediation_proposal": {
                                "target_device": "bldg:bacnet_device_301003",
                                "bacnet_uri": "bacnet://301003/BV:2",
                                "command": "Enable Stage-2 Auxiliary DX Cooling & Reset Supply Air Temp Setpoint to 54.0 F",
                                "priority_level": 8,
                            },
                        },
                    },
                ],
            },
            "OPTION_B_SCN4_SERVER_ROOM_PREDICTIVE_SLA": {
                "scenario_id": "SCN-4_CRITICAL_SERVER_ROOM_SLA",
                "button_label": "Option B — Trigger Critical Server Room Predictive Alert (ISS Server Room FCU)",
                "badge": "2 Predictive Alerts -> Tier-1 Mission Critical SLA Protection",
                "root_cause_node": "bldg:ec_1st_floor_ec_server_rm",
                "root_cause_dbid": "DBID:1:856291",
                "target_agent": "Predictive_Maintenance_And_SLA_Agent",
                "waves": [
                    {
                        "wave_index": 1,
                        "delay_seconds": 0,
                        "title": "TimesFM Anomaly Detection: 3.5x Stage-1 DX Compressor Short-Cycling",
                        "telemetry_override": {
                            "point_id": "bldg:ec_1st_floor_ec_server_rm__cool_1",
                            "previous_value": 1.0,
                            "injected_value": 3.5,
                            "unit": "CYCLES_PER_HR_RATIO",
                        },
                        "events": scn4_events[:1],
                        "affected_rooms": ["bldg:room_1f_server_rm"],
                    },
                    {
                        "wave_index": 2,
                        "delay_seconds": 3,
                        "title": "Tier-1 SLA Thermal Drift Warning (+1.8 F Creep -> 75.0 F SLA Breach in 3.5h) & Autonomous ADK 2.0 Action",
                        "telemetry_override": {
                            "point_id": "bldg:ec_1st_floor_ec_server_rm__space_temp",
                            "previous_value": 70.2,
                            "injected_value": 72.0,
                            "sla_limit": 75.0,
                            "unit": "DEG_F",
                        },
                        "events": scn4_events[1:2],
                        "affected_rooms": ["bldg:room_1f_server_rm"],
                        "autonomous_agent_action": {
                            "orchestrator": "ABO_Orchestrator_Agent",
                            "subagent": "Predictive_Maintenance_And_SLA_Agent",
                            "bqml_query_executed": "SELECT * FROM AI.DETECT_ANOMALIES(MODEL `acme_abo_telemetry.server_rm_forecaster`, ...)",
                            "collapsed_incident_title": "INC-1004: ISS Server Room FCU Compressor Short-Cycling (3.5x) & Imminent Tier-1 SLA Breach",
                            "hitl_remediation_proposal": {
                                "target_device": "bldg:bacnet_device_301101",
                                "bacnet_uri": "bacnet://301101/AV:4",
                                "command": "Widen Deadband +1.0 F to Stop Short-Cycling, Engage Auxiliary Chilled-Water Fan Coil & Dispatch Priority-1 Ticket",
                                "priority_level": 8,
                            },
                        },
                    },
                ],
            },
            "OPTIONAL_SCN2_MSTP102_BUS_STORM": {
                "scenario_id": "SCN-2_MSTP102_BUS_BOTTLENECK",
                "button_label": "Optional — Trigger BACnet MS/TP-102 Bus Storm & Subnet Mismatch (#301002 & #71101)",
                "events": scn2_events,
            },
            "OPTIONAL_SCN3_SILENT_ENERGY_BLEED": {
                "scenario_id": "SCN-3_SILENT_ENERGY_BLEED",
                "button_label": "Optional — Trigger 2nd-Floor Silent Energy Bleed Discovery ($18,400/yr)",
                "events": scn3_events,
            },
        },
    }
    (OUT_DIR / "live_injection_payloads.json").write_text(
        json.dumps(live_injection_payloads, indent=2), encoding="utf-8"
    )

    # Write golden_scenarios_manifest.json
    manifest = {
        "generated_at": "2026-10-23T14:15:00-04:00",
        "source_ontology": "ec_building_brick.ttl",
        "time_window": {
            "oldest_sample": "2026-09-09 00:00:00",
            "newest_sample": "2026-10-07 09:30:00",
            "interval_minutes": 15,
            "intervals_per_series": 2688,
        },
        "files_generated": {
            "portfolio_sites.csv": len(portfolio_rows),
            "equipment_nodes.csv": len(equip_rows),
            "spatial_nodes.csv": len(spatial_rows),
            "network_and_controller_nodes.csv": len(net_ctrl_rows),
            "graph_nodes.csv": len(graph_nodes),
            "graph_edges.csv": len(graph_edges),
            "point_catalog.csv": len(point_rows),
            "svweb_datasources.csv": len(datasources_rows),
            "telemetry_ts.csv": total_telemetry_rows,
            "bas_events.csv": len(bas_events),
            "bas_events_baseline.csv": len(bas_events_baseline),
            "live_injection_payloads.json": len(live_injection_payloads["live_scenarios"]),
        },
        "golden_scenarios": [
            {
                "scenario_id": "SCN-1_AHU1_COOLING_FAULT",
                "title": "Upstream Rooftop Unit Cooling Fault (bldg:area_ec_ahu_1 -> 14 1st-Floor Zone Alarms)",
                "active_alarms_count": 15,
                "root_cause_node": "bldg:area_ec_ahu_1",
                "root_cause_dbid": "DBID:1:856800",
            },
            {
                "scenario_id": "SCN-2_MSTP102_BUS_BOTTLENECK",
                "title": "BACnet MS/TP-102 Bus Bottleneck & Subnet Mask Mismatch (#301002 & #71101)",
                "active_alarms_count": 17,
                "root_cause_node": "bldg:bacnet_device_301002",
                "secondary_config_fault_node": "bldg:bacnet_device_71101",
            },
            {
                "scenario_id": "SCN-3_SILENT_ENERGY_BLEED",
                "title": "Silent Energy Bleed: Missing Night Setback (72.2F Night vs 72.0F Day), Rogue Reheat (PIU 2-1 42 kWh, PIU 2-20 26 kWh) & 24 Overrides",
                "active_alarms_count": 4,
                "quantified_annual_savings_usd": 18400,
            },
            {
                "scenario_id": "SCN-4_CRITICAL_SERVER_ROOM_SLA",
                "title": "Tier-1 Critical Space Predictive Protection (ISS Server Room FCU 3.5x Compressor Short-Cycling)",
                "active_alarms_count": 2,
                "root_cause_node": "bldg:ec_1st_floor_ec_server_rm",
                "root_cause_dbid": "DBID:1:856291",
            },
        ],
    }
    (OUT_DIR / "golden_scenarios_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print("Done! Summary:", json.dumps(manifest["files_generated"], indent=2))


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    generate_all()
