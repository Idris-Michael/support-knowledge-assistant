variable "subscription_id" {
  description = "Azure subscription to deploy into."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "uksouth"
}

variable "name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "skassist"
}

variable "image" {
  description = "Container image, e.g. myregistry.azurecr.io/support-knowledge-assistant:1.0.0"
  type        = string
}

variable "ollama_image" {
  description = "Ollama image serving nomic-embed-text (the embedding model the benchmark used)."
  type        = string
  default     = "ollama/ollama:0.9.0"
}

variable "model_gateway_url" {
  description = "Base URL of the organisation's model gateway, speaking the `ska-llm-proxy` API (POST /v1/complete)."
  type        = string
}

variable "operator_ip_ranges" {
  description = "CIDR ranges allowed to reach Key Vault's data plane (deployment pipeline, operators)."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = { project = "support-knowledge-assistant", environment = "pilot" }
}
