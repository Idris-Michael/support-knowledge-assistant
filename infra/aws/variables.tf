variable "region" {
  description = "AWS region."
  type        = string
  default     = "eu-west-2"
}

variable "name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "skassist"
}

variable "image" {
  description = "Container image URI, e.g. 123456789012.dkr.ecr.eu-west-2.amazonaws.com/support-knowledge-assistant:1.0.0"
  type        = string
}

variable "vpc_id" {
  description = "Existing VPC (most organisations hand over networking rather than let a project create it)."
  type        = string
}

variable "public_subnet_ids" {
  description = "Subnets for the load balancer."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Subnets for the tasks and the database (NAT needed for the model gateway and the model download)."
  type        = list(string)
}

variable "certificate_arn" {
  description = "ACM certificate for the HTTPS listener."
  type        = string
}

variable "api_count" {
  description = "API tasks (each with its own Ollama sidecar)."
  type        = number
  default     = 2
}

variable "ollama_image" {
  description = "Ollama image serving nomic-embed-text."
  type        = string
  default     = "ollama/ollama:0.9.0"
}

variable "model_gateway_url" {
  description = "Base URL of the organisation's model gateway, speaking the ska-llm-proxy API (POST /v1/complete)."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = { project = "support-knowledge-assistant", environment = "pilot" }
}
