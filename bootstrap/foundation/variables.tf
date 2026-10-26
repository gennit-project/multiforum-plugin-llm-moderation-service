variable "project_id" {
  type        = string
  description = "GCP project that owns the Terraform state bucket."
}

variable "region" {
  type        = string
  description = "GCP location for the state bucket."
  default     = "us-central1"
}

variable "state_bucket_name" {
  type        = string
  description = "Globally unique GCS bucket used by bootstrap and deployment Terraform state."
}
