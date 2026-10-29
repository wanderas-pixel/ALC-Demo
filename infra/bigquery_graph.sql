-- =============================================================================
-- ACME Co. Autonomous Building Operations (ABO)
-- BigQuery Relational Schema, Dual-Topology Property Graph & BQML Definitions
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS `acme_abo_telemetry`
OPTIONS (
  location = 'US',
  description = 'ACME Co. Autonomous Building Operations Semantic Property Graph & Time-Series Telemetry'
);

-- 1. Portfolio Sites Table (5 Enterprise Facilities)
CREATE OR REPLACE TABLE `acme_abo_telemetry.portfolio_sites` (
  site_id STRING NOT NULL,
  site_name STRING,
  city STRING,
  facility_type STRING,
  gross_sqft INT64,
  floors_count INT64,
  equipment_count INT64,
  bacnet_controllers_count INT64,
  active_raw_alarms INT64,
  correlated_incidents INT64,
  alarm_noise_reduction_pct FLOAT64,
  mttr_baseline_hours FLOAT64,
  mttr_autonomous_minutes FLOAT64,
  zone_comfort_compliance_pct FLOAT64,
  identified_annual_energy_savings_usd INT64,
  identified_co2_reduction_tons FLOAT64,
  sla_status STRING
);

-- 2. Equipment Nodes Table (126 Rows from ec_building_brick.ttl)
CREATE OR REPLACE TABLE `acme_abo_telemetry.equipment_nodes` (
  node_id STRING NOT NULL,
  site_id STRING,
  brick_class STRING,
  ashrae_223p_class STRING,
  label STRING,
  dbid STRING,
  geographic_path STRING,
  floor_id STRING,
  room_id STRING,
  serving_ahu_id STRING,
  controller_id STRING,
  program_id STRING,
  program_name STRING,
  template STRING,
  class_rule STRING,
  class_rule_source STRING,
  class_confidence STRING,
  floor_basis STRING,
  core_evidence STRING,
  point_count INT64,
  has_trend_data BOOL
);

-- 3. Spatial Nodes Table (38 Rows: 1 Building + 3 Floors + 34 REC Rooms)
CREATE OR REPLACE TABLE `acme_abo_telemetry.spatial_nodes` (
  space_id STRING NOT NULL,
  space_type STRING,
  label STRING,
  parent_space_id STRING,
  dbid STRING,
  geographic_path STRING,
  sla_criticality_tier STRING,
  weekday_daytime_occupancy_pct FLOAT64,
  comfort_pct_within_1f FLOAT64,
  served_by_equipment_ids STRING
);

-- 4. Network & Controller Nodes Table (100 Rows: 7 Networks + 3 Inferred Hubs + 90 Controllers)
CREATE OR REPLACE TABLE `acme_abo_telemetry.network_and_controller_nodes` (
  node_id STRING NOT NULL,
  entity_category STRING,
  label STRING,
  controller_model STRING,
  device_type STRING,
  media_type STRING,
  network_id STRING,
  network_number STRING,
  physical_shape STRING,
  mac_address STRING,
  ip_address STRING,
  subnet_mask STRING,
  default_gateway STRING,
  serial_number STRING,
  dbid STRING,
  is_router BOOL,
  routes_to_Or_behind_router STRING,
  config_anomaly_flag STRING
);

-- 5. Unified Property Graph Nodes Table (250 Rows)
CREATE OR REPLACE TABLE `acme_abo_telemetry.graph_nodes` (
  node_id STRING NOT NULL,
  node_category STRING,
  ontology_class STRING,
  label STRING,
  dbid STRING,
  floor_id STRING,
  network_id STRING,
  sla_tier STRING,
  metadata_json STRING
);

-- 6. Unified Property Graph Edges Table (410 Rows)
CREATE OR REPLACE TABLE `acme_abo_telemetry.graph_edges` (
  edge_id STRING NOT NULL,
  source_node_id STRING NOT NULL,
  target_node_id STRING NOT NULL,
  edge_type STRING NOT NULL,
  ontology_predicate STRING,
  confidence STRING
);

-- 7. Point Catalog Table (1,653 Modeled Brick/223P Points)
CREATE OR REPLACE TABLE `acme_abo_telemetry.point_catalog` (
  point_id STRING NOT NULL,
  equipment_id STRING,
  brick_class STRING,
  label STRING,
  unit STRING,
  point_ref STRING,
  bacnet_block STRING,
  class_rule STRING,
  class_confidence STRING,
  bacnet_uri STRING,
  bacnet_object_type STRING,
  bacnet_object_id STRING,
  bacnet_device_id STRING,
  has_timeseries BOOL,
  timeseries_id STRING,
  series_table STRING,
  is_active_350_demo_series BOOL,
  match_basis STRING,
  match_status STRING,
  historical_record_count INT64,
  oldest_sample STRING,
  newest_sample STRING,
  golden_scenario_id STRING
);

-- 8. SVWEB.DATASOURCES Active Trend Registry (350 Series)
CREATE OR REPLACE TABLE `acme_abo_telemetry.svweb_datasources` (
  tid STRING NOT NULL,
  series_table STRING,
  point_id STRING,
  equipment_id STRING,
  brick_class STRING,
  unit STRING,
  sampling_interval_minutes INT64,
  sample_count INT64,
  oldest_sample STRING,
  newest_sample STRING,
  match_status STRING,
  golden_scenario_id STRING
);

-- 9. Time-Series Telemetry Table (940,800 Rows — Partitioned by Day, Clustered by equipment_id, point_id)
CREATE OR REPLACE TABLE `acme_abo_telemetry.telemetry_ts` (
  series_table STRING,
  point_id STRING,
  equipment_id STRING,
  timestamp TIMESTAMP,
  value FLOAT64,
  unit STRING,
  quality_flag STRING,
  scenario_tag STRING
)
PARTITION BY DATE(timestamp)
CLUSTER BY equipment_id, point_id;

-- 10. BAS Events & Alarms Table (360 Rows: 322 Historical + 38 Active Golden Scenarios)
CREATE OR REPLACE TABLE `acme_abo_telemetry.bas_events` (
  event_id STRING NOT NULL,
  timestamp TIMESTAMP,
  equipment_id STRING,
  controller_id STRING,
  network_id STRING,
  event_category STRING,
  severity STRING,
  status STRING,
  golden_scenario_id STRING,
  message STRING
);

-- 11. Clean T=0 Baseline Events Table (322 Historical Cleared Rows Only)
CREATE OR REPLACE TABLE `acme_abo_telemetry.bas_events_baseline` (
  event_id STRING NOT NULL,
  timestamp TIMESTAMP,
  equipment_id STRING,
  controller_id STRING,
  network_id STRING,
  event_category STRING,
  severity STRING,
  status STRING,
  golden_scenario_id STRING,
  message STRING
);

-- =============================================================================
-- 12. BigQuery Dual-Topology Property Graph DDL (ISO GQL / GRAPH_TABLE)
-- =============================================================================
CREATE OR REPLACE PROPERTY GRAPH `acme_abo_telemetry.acme_building_graph`
  NODE TABLES (
    `acme_abo_telemetry.graph_nodes` AS graph_nodes
      KEY (node_id)
      LABEL Entity
      PROPERTIES (
        node_id,
        node_category,
        ontology_class,
        label,
        dbid,
        floor_id,
        network_id,
        sla_tier,
        metadata_json
      )
  )
  EDGE TABLES (
    `acme_abo_telemetry.graph_edges` AS graph_edges
      KEY (edge_id)
      SOURCE KEY (source_node_id) REFERENCES graph_nodes (node_id)
      DESTINATION KEY (target_node_id) REFERENCES graph_nodes (node_id)
      LABEL CONNECTS
      PROPERTIES (
        edge_id,
        edge_type,
        ontology_predicate,
        confidence
      )
  );

-- =============================================================================
-- 13. Peer-Cohort Z-Score Analytical View (Joining Property Graph + Telemetry)
-- =============================================================================
CREATE OR REPLACE VIEW `acme_abo_telemetry.v_peer_cohort_anomalies` AS
WITH hvac_cohorts AS (
  SELECT
    ahu_id,
    ahu_label,
    terminal_id,
    terminal_label
  FROM GRAPH_TABLE (
    `acme_abo_telemetry.acme_building_graph`
    MATCH (ahu:Entity)-[e:CONNECTS WHERE e.edge_type = 'FEEDS']->(term:Entity)
    COLUMNS (
      ahu.node_id AS ahu_id,
      ahu.label AS ahu_label,
      term.node_id AS terminal_id,
      term.label AS terminal_label
    )
  )
),
latest_zone_temps AS (
  SELECT
    t.equipment_id,
    t.point_id,
    AVG(t.value) AS avg_value_last_4h
  FROM `acme_abo_telemetry.telemetry_ts` t
  WHERE t.timestamp >= TIMESTAMP('2026-10-07 05:30:00')
  GROUP BY t.equipment_id, t.point_id
)
SELECT
  c.ahu_id,
  c.ahu_label,
  c.terminal_id,
  c.terminal_label,
  l.point_id,
  l.avg_value_last_4h,
  AVG(l.avg_value_last_4h) OVER (PARTITION BY c.ahu_id) AS cohort_mean,
  SAFE_DIVIDE(
    l.avg_value_last_4h - AVG(l.avg_value_last_4h) OVER (PARTITION BY c.ahu_id),
    NULLIF(STDDEV_POP(l.avg_value_last_4h) OVER (PARTITION BY c.ahu_id), 0)
  ) AS peer_z_score
FROM hvac_cohorts c
JOIN latest_zone_temps l
  ON c.terminal_id = l.equipment_id;

