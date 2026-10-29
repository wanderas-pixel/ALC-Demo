# ACME Co. Autonomous Building Operations — Synthetic Source Data Catalog

This folder (`Source Data/`) contains the complete, deterministic synthetic dataset for the **ACME Co. Autonomous Building Operations (ABO)** demonstration, anchored on the **ACME Emerald Crest HQ** hero facility and 4 regional ACME Co. portfolio sites.

All datasets are deterministically generated from [`ec_building_brick.ttl`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/ec_building_brick.ttl), [`floor_view.html`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/floor_view.html), and [`network_topology.html`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/network_topology.html) using [`generate_acme_demo_data.py`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/generate_acme_demo_data.py) (`random.seed(42)`).

---

## 1. Generated Files & Exact Row Counts

| File Name | Target BigQuery Table (`acme_abo_telemetry`) | Exact Row Count | Description |
| :--- | :--- | :---: | :--- |
| [`portfolio_sites.csv`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/portfolio_sites.csv) | `acme_abo_telemetry.portfolio_sites` | **5** | 5 ACME Co. enterprise facilities (`ACME-SITE-001` Hero Site + 4 regional hubs) with executive KPIs (89.5% alarm noise reduction, MTTR from 4.2 hrs to 8 min, \$18,400/yr savings). |
| [`equipment_nodes.csv`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/equipment_nodes.csv) | `acme_abo_telemetry.equipment_nodes` | **126** | All 126 HVAC, lighting, irrigation, and zone controller equipment entities from `ec_building_brick.ttl` (`2` Rooftop AHUs, `23` VAVs, `22` PIUs, `49` FCUs, `30` auxiliary/control assets) with `bsm:dbid`, `bsm:path`, `bsm:template`, `bsm:program`, `bsm:classRule`, and `bsm:coreEvidence`. |
| [`spatial_nodes.csv`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/spatial_nodes.csv) | `acme_abo_telemetry.spatial_nodes` | **38** | Full spatial hierarchy (`1` `rec:Building`, `3` `rec:Floor` levels, and `34` `rec:Room` spaces) enriched with SLA Criticality Tiers (`Tier-1 Mission Critical` for `ISS Server Room`), weekday daytime occupancy %, and comfort compliance %. |
| [`network_and_controller_nodes.csv`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/network_and_controller_nodes.csv) | `acme_abo_telemetry.network_and_controller_nodes` | **100** | `7` `bsm:Network` segments (`888`, `2401`, `102`, `2001`, `3011`, `30100`, `4401`), `3` `bsm:InferredNetworkDevice` hubs/gateways, and `90` BACnet routers/controllers (`#301002`, `#71101`, `#301003`, `#301004`, `#301005`, `#260000`, etc.). |
| [`graph_nodes.csv`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/graph_nodes.csv) | `acme_abo_telemetry.graph_nodes` | **250** | Unified node table for the `CREATE OR REPLACE PROPERTY GRAPH acme_abo_telemetry.acme_building_graph` DDL in BigQuery Graph. |
| [`graph_edges.csv`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/graph_edges.csv) | `acme_abo_telemetry.graph_edges` | **410** | Unified directed edge table (`FEEDS`, `LOCATED_IN`, `CONTROLLED_BY`, `ON_NETWORK`, `ROUTES_TO`, `BEHIND_ROUTER`, `PART_OF`, `HOSTED_ON_CONTROLLER`) for multi-hop ISO GQL traversal. |
| [`point_catalog.csv`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/point_catalog.csv) | `acme_abo_telemetry.point_catalog` | **1,653** | All 1,653 Brick/223P sensor, setpoint, status, and command points from `ec_building_brick.ttl` with BACnet object references (`ref:BACnetReference`) and `SVWEB` trend mappings (`ref:TimeseriesReference`). |
| [`svweb_datasources.csv`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/svweb_datasources.csv) | `acme_abo_telemetry.svweb_datasources` | **350** | Catalog of the 350 active trend series (`272` original `SVWEB.DATASERIES_*` series + `78` augmented `ref:BACnetReference` series) sampled at 15-minute intervals. |
| [`telemetry_ts.csv`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/telemetry_ts.csv) | `acme_abo_telemetry.telemetry_ts` | **940,800** | Complete 28-day time-series dataset (`350` series $\times$ `2,688` 15-minute intervals from `2026-09-09 00:00:00` to `2026-10-07 09:30:00`). |
| [`telemetry_ts_last_24h_sample.csv`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/telemetry_ts_last_24h_sample.csv) | *(Quick Inspection Sample)* | **3,840** | Lightweight 24-hour slice (`40` priority series $\times$ `96` 15-minute intervals) for rapid local chart previewing and unit testing. |
| [`bas_events.csv`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/bas_events.csv) | `acme_abo_telemetry.bas_events` | **360** | `322` historical Trail Guide / override events (`PIU 5` = 44 total, `PIU 10` = 41 total, `PIU 1` = 8 total, `24` irrigation/HVAC overrides) + `38` active alarms across the 4 Golden Scenarios. |
| [`bas_events_baseline.csv`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/bas_events_baseline.csv) | `acme_abo_telemetry.bas_events_baseline` | **322** | Clean `T=0` baseline events table (`322` historical cleared events, `0` active unacknowledged alarms) used when the demo starts in a healthy state before live fault injection. |
| [`live_injection_payloads.json`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/live_injection_payloads.json) | *(Companion Admin UI `/admin` & SSE Simulator)* | **4 Scenarios** | Wave-by-wave real-time event and telemetry payloads for **Option A (`SCN-1`: Cascading Rooftop Unit Failure)** and **Option B (`SCN-4`: Critical Server Room Predictive Alert)**, plus optional triggers for `SCN-2`/`SCN-3` and instant `<1s` reset state. |
| [`golden_scenarios_manifest.json`](file:///Users/wanderas/Documents/gcp/ALC%20-%20Demo/Source%20Data/golden_scenarios_manifest.json) | *(Verification Manifest)* | — | JSON manifest documenting generation metadata, exact row counts, and the 4 Golden Scenarios. |

---

## 2. Embedded Golden Scenarios Summary

1. **`SCN-1_AHU1_COOLING_FAULT` (15 Active Alarms $\rightarrow$ 1 Root Cause):**
   - Root Cause: `bldg:area_ec_ahu_1` (`RTU-1 (ACME) BACnet Integration to UPC`, `DBID:1:856800`) Stage-1 DX compressor trip causing Supply Air Temperature (`__sat`) to drift from `55.0 °F` to `68.5 °F` over the final 4 hours (`2026-10-07 05:45` – `09:30`).
   - Downstream Cascade: 14 1st-floor terminal units (`PIU 1` through `PIU 10`, `VAV 1`, `VAV 2`, `VAV 4`, `VAV 5`) report high zone temperatures (`> 76.2 °F`) and 100% damper saturation.
2. **`SCN-2_MSTP102_BUS_BOTTLENECK` (17 Active Alarms $\rightarrow$ 1 Root Cause):**
   - Root Cause: `Router: 02 AMR/UNI-32` (`bldg:bacnet_device_301002`) RS-485 bus `MSTP-102` experiencing 42% APDU packet loss across 16 downstream channels, compounded by subnet mask mismatch on `MES eBox - Showcase` (`bldg:bacnet_device_71101`, `172.31.222.99` configured with `255.255.255.0` on a `/26` subnet `255.255.255.192`).
3. **`SCN-3_SILENT_ENERGY_BLEED` (4 Active Analytics Alerts $\rightarrow$ \$18,400/yr Savings):**
   - Missing 2nd-floor night setback (`72.2 °F` night average vs. `72.0 °F` daytime average, `37%` night fan runtime, `PIU 2-8` flowing `394 cfm` at night vs. `183 cfm` daytime), rogue electric reheat on `PIU 2-1` (`42 kWh`, 54% of floor reheat) and `PIU 2-20` (`26 kWh`), and `24` manual overrides totaling `235 minutes`.
4. **`SCN-4_CRITICAL_SERVER_ROOM_SLA` (2 Active Predictive Alerts $\rightarrow$ Tier-1 SLA Protection):**
   - `ISS Server Room` (`bldg:ec_1st_floor_ec_server_rm`, `DBID:1:856291`, `Tier-1 Mission Critical`) Stage-1 DX cooling `cycle_count` spiked $3.5\times$ over the last 24 hours while zone temperature crept $+1.8\text{ }^\circ\text{F}$ (`70.2 °F` $\rightarrow$ `72.0 °F`), heading toward the `75.0 °F` SLA threshold.

---

## 3. Regenerating the Dataset

To regenerate all files deterministically from scratch (using only the Python 3 standard library):

```bash
python3 "Source Data/generate_acme_demo_data.py"
```

