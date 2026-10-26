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
