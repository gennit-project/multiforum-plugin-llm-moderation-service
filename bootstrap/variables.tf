variable "project_id" {
  type        = string
  description = "GCP project that hosts the moderation service."
}

variable "region" {
  type        = string
  description = "GCP region for the state bucket and service."
  default     = "us-central1"
}

variable "state_bucket_name" {
  type        = string
  description = "Globally unique GCS bucket used by bootstrap and deployment Terraform state."
}

variable "github_owner" {
  type        = string
  description = "GitHub organization that owns the service repository."
  default     = "gennit-project"
}

variable "github_repository" {
  type        = string
  description = "GitHub repository name without its owner."
  default     = "multiforum-plugin-llm-moderation-service"
}

variable "production_reviewer_team_ids" {
  type        = list(number)
  description = "GitHub team database IDs allowed to approve production deployments."

  validation {
    condition     = length(var.production_reviewer_team_ids) > 0
    error_message = "At least one production environment reviewer team ID is required."
  }
}

variable "deploy_service_account_id" {
  type        = string
  description = "Account ID for the GitHub Actions deployment identity."
  default     = "llm-moderation-deployer"
}

variable "workload_identity_pool_id" {
  type        = string
  description = "Workload Identity pool ID shared by GitHub Actions providers."
  default     = "github-actions"
}

variable "workload_identity_provider_id" {
  type        = string
  description = "Repository-specific Workload Identity provider ID."
  default     = "llm-moderation-service"
}

variable "multiforum_graphql_url" {
  type        = string
  description = "Production Multiforum GraphQL HTTPS endpoint used by the E2E smoke workflow."

  validation {
    condition     = can(regex("^https://[^/]+", var.multiforum_graphql_url))
    error_message = "multiforum_graphql_url must be an absolute HTTPS URL."
  }
}

variable "multiforum_oauth_token_url" {
  type        = string
  description = "OAuth HTTPS token endpoint used by the dedicated smoke identity."

  validation {
    condition     = can(regex("^https://[^/]+", var.multiforum_oauth_token_url))
    error_message = "multiforum_oauth_token_url must be an absolute HTTPS URL."
  }
}

variable "multiforum_oauth_client_id" {
  type        = string
  description = "Public OAuth client identifier used by the smoke workflow."

  validation {
    condition     = trimspace(var.multiforum_oauth_client_id) != ""
    error_message = "multiforum_oauth_client_id must not be empty."
  }
}

variable "multiforum_oauth_audience" {
  type        = string
  description = "Multiforum API audience requested for the smoke identity."

  validation {
    condition     = trimspace(var.multiforum_oauth_audience) != ""
    error_message = "multiforum_oauth_audience must not be empty."
  }
}

variable "multiforum_oauth_realm" {
  type        = string
  description = "OAuth password-realm connection containing the dedicated smoke identity."
  default     = "Username-Password-Authentication"

  validation {
    condition     = trimspace(var.multiforum_oauth_realm) != ""
    error_message = "multiforum_oauth_realm must not be empty."
  }
}

variable "multiforum_smoke_forum" {
  type        = string
  description = "Dedicated forum allowlisted for production LLM moderation smoke tests."

  validation {
    condition     = trimspace(var.multiforum_smoke_forum) != ""
    error_message = "multiforum_smoke_forum must not be empty."
  }
}

variable "multiforum_smoke_author_username" {
  type        = string
  description = "Persisted Multiforum username belonging to the dedicated smoke identity."

  validation {
    condition     = trimspace(var.multiforum_smoke_author_username) != ""
    error_message = "multiforum_smoke_author_username must not be empty."
  }
}

variable "multiforum_smoke_expected_rule" {
  type        = string
  description = "Exact canonical server rule the synthetic smoke content must cite."

  validation {
    condition     = trimspace(var.multiforum_smoke_expected_rule) != ""
    error_message = "multiforum_smoke_expected_rule must not be empty."
  }
}
