variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "environment" {
  type        = string
  description = "Deployment environment name used for labels and state separation."
  default     = "production"
}

variable "region" {
  type        = string
  description = "Cloud Run region."
  default     = "us-central1"
}

variable "service_name" {
  type    = string
  default = "llm-moderation-service"
}

variable "runtime_service_account_id" {
  type        = string
  description = "Account ID for the dedicated Cloud Run runtime identity."
  default     = "llm-moderation-runtime"
}

variable "image" {
  type        = string
  description = "Fully-qualified immutable container image to deploy."
}

variable "artifact_repository" {
  type        = string
  description = "Dedicated Artifact Registry repository for moderation-service images."
  default     = "multiforum-llm-moderation"
}

variable "deployment_revision" {
  type        = string
  description = "Deployment identifier that forces a revision when secrets rotate."
  default     = "manual"
}

variable "allow_unauthenticated" {
  type        = bool
  description = "Allow requests to reach FastAPI; /moderate still requires X-API-Key."
  default     = true
}

variable "min_instance_count" {
  type        = number
  description = "Minimum number of warm Cloud Run instances."
  default     = 0

  validation {
    condition     = var.min_instance_count >= 0
    error_message = "min_instance_count cannot be negative."
  }
}

variable "max_instance_count" {
  type        = number
  description = "Maximum Cloud Run instances. Keep at one while rate limits are per-instance."
  default     = 1

  validation {
    condition     = var.max_instance_count >= 1
    error_message = "max_instance_count must be at least 1."
  }
}

variable "container_concurrency" {
  type        = number
  description = "Maximum simultaneous HTTP requests handled by one Cloud Run instance."
  default     = 4

  validation {
    condition     = var.container_concurrency >= 1 && var.container_concurrency <= 1000
    error_message = "container_concurrency must be between 1 and 1000."
  }
}

variable "api_key_secret_id" {
  type        = string
  description = "Secret Manager ID containing the shared service API key."
  default     = "llm-moderation-api-key"
}

variable "provider_api_key_secret_id" {
  type        = string
  description = "Secret Manager ID containing the LLM provider API key."
  default     = "llm-moderation-provider-api-key"
}

variable "provider_base_url" {
  type        = string
  description = "OpenAI-compatible provider base URL."
  default     = "https://api.openai.com/v1"
}

variable "provider_model" {
  type        = string
  description = "Default provider model."
  default     = "gpt-4o-mini"
}

variable "provider_timeout_seconds" {
  type        = number
  description = "Timeout for one provider attempt."
  default     = 30

  validation {
    condition     = var.provider_timeout_seconds > 0 && var.provider_timeout_seconds <= 120
    error_message = "provider_timeout_seconds must be greater than 0 and at most 120."
  }
}

variable "provider_concurrency" {
  type        = number
  description = "Provider calls allowed in flight per service instance."
  default     = 2

  validation {
    condition     = var.provider_concurrency >= 1 && var.provider_concurrency <= 100
    error_message = "provider_concurrency must be between 1 and 100."
  }
}

variable "provider_rate_limit_per_minute" {
  type        = number
  description = "Provider call starts allowed per minute per service instance."
  default     = 30

  validation {
    condition     = var.provider_rate_limit_per_minute >= 1 && var.provider_rate_limit_per_minute <= 10000
    error_message = "provider_rate_limit_per_minute must be between 1 and 10000."
  }
}

variable "provider_max_attempts" {
  type        = number
  description = "Maximum attempts for a transient provider failure."
  default     = 3

  validation {
    condition     = var.provider_max_attempts >= 1 && var.provider_max_attempts <= 10
    error_message = "provider_max_attempts must be between 1 and 10."
  }
}

variable "provider_retry_base_seconds" {
  type        = number
  description = "Initial provider retry delay."
  default     = 0.25

  validation {
    condition     = var.provider_retry_base_seconds >= 0 && var.provider_retry_base_seconds <= 30
    error_message = "provider_retry_base_seconds must be between 0 and 30."
  }
}

variable "provider_retry_max_seconds" {
  type        = number
  description = "Maximum retry delay held inside one service request."
  default     = 5

  validation {
    condition     = var.provider_retry_max_seconds > 0 && var.provider_retry_max_seconds <= 120
    error_message = "provider_retry_max_seconds must be greater than 0 and at most 120."
  }
}
