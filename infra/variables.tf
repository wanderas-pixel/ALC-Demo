variable "project_id" {
  description = "Target Google Cloud Project ID for the ACME Co. Autonomous Building Operations (ABO) Demo"
  type        = string
  default     = "genai-demos-391416"
}

variable "region" {
  description = "Primary GCP region for Agent Platform Runtime, Agent Gateway, Agent Registry, Cloud Run, and Cloud Workflows"
  type        = string
  default     = "us-central1"
}

variable "bq_dataset_id" {
  description = "BigQuery dataset ID housing the semantic graph, SVWEB.DATASOURCES, and telemetry tables"
  type        = string
  default     = "acme_abo_telemetry"
}

variable "llm_model" {
  description = "Vertex AI Gemini model used across ADK 2.0 agents on Agent Platform Runtime and SHACL-as-Reward pipelines"
  type        = string
  default     = "gemini-3.8-flash"
}

variable "agent_runtime_name" {
  description = "Google Cloud Agent Platform Runtime instance name"
  type        = string
  default     = "acme-abo-agent-platform-runtime"
}

variable "agent_gateway_name" {
  description = "Google Cloud Agent Gateway instance name fronting the Agent Platform Runtime"
  type        = string
  default     = "acme-abo-agent-gateway"
}

variable "agent_registry_name" {
  description = "Google Cloud Agent Registry instance name cataloging A2A Agent Cards and capabilities"
  type        = string
  default     = "acme-abo-agent-registry"
}
