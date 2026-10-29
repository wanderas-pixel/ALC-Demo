terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. Enable Managed First-Party GCP APIs (Including Agent Platform, Gateway, Registry & OTel)
locals {
  services = [
    "bigquery.googleapis.com",
    "aiplatform.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "pubsub.googleapis.com",
    "workflows.googleapis.com",
    "iap.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudtrace.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "telemetry.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
  ]
}

resource "google_project_service" "enabled_apis" {
  for_each           = toset(local.services)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# 2. Cryptographic Per-Agent Identities (Agent Identity) & Platform Service Accounts
resource "google_service_account" "sa_onboarding" {
  account_id   = "sa-onboarding-workflow"
  display_name = "ACME ABO SHACL-as-Reward Ontology Onboarding Workflow SA"
}

resource "google_service_account" "sa_simulator" {
  account_id   = "sa-telemetry-simulator"
  display_name = "ACME ABO Telemetry & Live Fault Simulator SA"
}

resource "google_service_account" "sa_agent_gateway" {
  account_id   = "sa-abo-agent-gateway"
  display_name = "ACME ABO Agent Gateway Ingress/Egress Policy & OTel Proxy Identity"
}

resource "google_service_account" "sa_agent_supervisor" {
  account_id   = "sa-agent-supervisor"
  display_name = "ACME ABO Agent Identity — Root Supervisor Agent (abo_supervisor_agent)"
}

resource "google_service_account" "sa_agent_triage" {
  account_id   = "sa-agent-triage"
  display_name = "ACME ABO Agent Identity — Alarm Triage & Storm Dedup Agent (alarm_triage_agent)"
}

resource "google_service_account" "sa_agent_rca" {
  account_id   = "sa-agent-rca"
  display_name = "ACME ABO Agent Identity — Cross-Layer RCA Agent (cross_layer_rca_agent)"
}

resource "google_service_account" "sa_agent_energy" {
  account_id   = "sa-agent-energy"
  display_name = "ACME ABO Agent Identity — Energy & Drift Optimizer Agent (energy_optimization_agent)"
}

resource "google_service_account" "sa_agent_remediation" {
  account_id   = "sa-agent-remediation"
  display_name = "ACME ABO Agent Identity — HITL BACnet Priority-8 Remediation Agent (remediation_dispatch_agent)"
}

resource "google_service_account" "sa_cockpit" {
  account_id   = "sa-cockpit-cloudrun"
  display_name = "ACME ABO Cloud Run Operations Cockpit & BFF SA"
}

locals {
  agent_identity_emails = [
    google_service_account.sa_agent_gateway.email,
    google_service_account.sa_agent_supervisor.email,
    google_service_account.sa_agent_triage.email,
    google_service_account.sa_agent_rca.email,
    google_service_account.sa_agent_energy.email,
    google_service_account.sa_agent_remediation.email,
  ]
}

# 3. Cloud Storage Staging Bucket for BAS Backups, Brick Ontology & Agent Registry Manifests
resource "google_storage_bucket" "building_exports" {
  name                        = "${var.project_id}-acme-abo-building-exports"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  depends_on                  = [google_project_service.enabled_apis]
}

# 4. Cloud Pub/Sub Topics for Live Telemetry, Dynamic Alarm Injection & Agent Gateway Events
resource "google_pubsub_topic" "dataseries_stream" {
  name       = "acme-dataseries-stream"
  depends_on = [google_project_service.enabled_apis]
}

resource "google_pubsub_topic" "bas_alarms" {
  name       = "acme-bas-alarms"
  depends_on = [google_project_service.enabled_apis]
}

resource "google_pubsub_topic" "agent_otel_events" {
  name       = "acme-agent-platform-otel-events"
  depends_on = [google_project_service.enabled_apis]
}

# 5. BigQuery Dataset for Property Graph, SVWEB.DATASOURCES, and Telemetry
resource "google_bigquery_dataset" "acme_abo" {
  dataset_id  = var.bq_dataset_id
  location    = "US"
  description = "ACME Co. Autonomous Building Operations Semantic Property Graph & Time-Series Telemetry"
  depends_on  = [google_project_service.enabled_apis]
}

# 6. Scoped Per-Agent Identity IAM Bindings & Full OpenTelemetry (OTel) Observability Roles
resource "google_project_iam_member" "agent_identities_bq_viewer" {
  for_each = toset(local.agent_identity_emails)
  project  = var.project_id
  role     = "roles/bigquery.dataViewer"
  member   = "serviceAccount:${each.value}"
}

resource "google_project_iam_member" "agent_identities_bq_job_user" {
  for_each = toset(local.agent_identity_emails)
  project  = var.project_id
  role     = "roles/bigquery.jobUser"
  member   = "serviceAccount:${each.value}"
}

resource "google_project_iam_member" "agent_identities_vertex_user" {
  for_each = toset(local.agent_identity_emails)
  project  = var.project_id
  role     = "roles/aiplatform.user"
  member   = "serviceAccount:${each.value}"
}

# Full OpenTelemetry (OTel) Trace, Metrics & Log Export Permissions for Agent Platform Runtime
resource "google_project_iam_member" "agent_identities_otel_trace" {
  for_each = toset(local.agent_identity_emails)
  project  = var.project_id
  role     = "roles/cloudtrace.agent"
  member   = "serviceAccount:${each.value}"
}

resource "google_project_iam_member" "agent_identities_otel_metrics" {
  for_each = toset(local.agent_identity_emails)
  project  = var.project_id
  role     = "roles/monitoring.metricWriter"
  member   = "serviceAccount:${each.value}"
}

resource "google_project_iam_member" "agent_identities_otel_logs" {
  for_each = toset(local.agent_identity_emails)
  project  = var.project_id
  role     = "roles/logging.logWriter"
  member   = "serviceAccount:${each.value}"
}

# Only sa-agent-remediation is authorized to invoke the SHACL-gated BACnet Priority 8 Workflow
resource "google_project_iam_member" "remediation_workflow_invoker" {
  project = var.project_id
  role    = "roles/workflows.invoker"
  member  = "serviceAccount:${google_service_account.sa_agent_remediation.email}"
}

resource "google_project_iam_member" "cockpit_bq_viewer" {
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.sa_cockpit.email}"
}

resource "google_project_iam_member" "cockpit_bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.sa_cockpit.email}"
}

resource "google_project_iam_member" "cockpit_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.sa_cockpit.email}"
}

# Hardened Cloud Run v2 Service for the Operations Cockpit (/) and Admin Director Console (/admin)
resource "google_cloud_run_v2_service" "cockpit" {
  name     = "acme-abo-cockpit"
  location = var.region
  project  = var.project_id

  # Restrict ingress to Internal + Cloud Load Balancing (IAP + Cloud Armor), blocking direct *.run.app bypass
  ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    service_account       = google_service_account.sa_cockpit.email
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

    scaling {
      min_instance_count = 1
      max_instance_count = 10
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/acme-abo-repo/acme-abo-cockpit:latest"

      ports {
        container_port = 8080
      }

      env {
        name  = "ACME_ENFORCE_IAP"
        value = "true"
      }
      env {
        name  = "ACME_AGENT_RUNTIME"
        value = var.agent_runtime_name
      }
      env {
        name  = "ACME_AGENT_GATEWAY"
        value = var.agent_gateway_name
      }
      env {
        name  = "ACME_AGENT_REGISTRY"
        value = var.agent_registry_name
      }
    }
  }

  depends_on = [google_project_service.enabled_apis]
}

# Hardened Cloud Run v2 Job for 1-Click Synthetic Baseline Reset & Seed Generation
resource "google_cloud_run_v2_job" "data_reset" {
  name     = "acme-abo-data-reset"
  location = var.region
  project  = var.project_id

  template {
    template {
      service_account       = google_service_account.sa_simulator.email
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
      max_retries           = 1

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/acme-abo-repo/acme-abo-data-generator:latest"
      }
    }
  }

  depends_on = [google_project_service.enabled_apis]
}


