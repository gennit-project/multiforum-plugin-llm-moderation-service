terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  labels = {
    application = "multiforum"
    component   = "llm-moderation"
    environment = var.environment
    managed_by  = "terraform"
  }

  required_services = toset([
    "artifactregistry.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = var.artifact_repository
  description   = "Container images for the Multiforum LLM moderation service"
  format        = "DOCKER"
  labels        = local.labels

  depends_on = [google_project_service.required]
}

# Terraform owns secret containers and IAM only. The deployment workflow adds
# secret versions with gcloud so plaintext never enters Terraform state.
resource "google_secret_manager_secret" "api_key" {
  secret_id = var.api_key_secret_id
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "provider_api_key" {
  secret_id = var.provider_api_key_secret_id
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_service_account" "runtime" {
  account_id   = var.runtime_service_account_id
  display_name = "LLM moderation service runtime"
}

resource "google_secret_manager_secret_iam_member" "api_key_access" {
  secret_id = google_secret_manager_secret.api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "provider_key_access" {
  secret_id = google_secret_manager_secret.provider_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_run_v2_service" "service" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = local.labels

  lifecycle {
    precondition {
      condition     = var.max_instance_count >= var.min_instance_count
      error_message = "max_instance_count must be greater than or equal to min_instance_count."
    }
  }

  template {
    labels = {
      deployment_revision = var.deployment_revision
    }

    service_account                  = google_service_account.runtime.email
    timeout                          = "120s"
    max_instance_request_concurrency = var.container_concurrency

    scaling {
      min_instance_count = var.min_instance_count
      max_instance_count = var.max_instance_count
    }

    containers {
      image = var.image

      ports {
        container_port = 8080
      }

      env {
        name = "MOD_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "MOD_PROVIDER_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.provider_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "MOD_PROVIDER_BASE_URL"
        value = var.provider_base_url
      }

      env {
        name  = "MOD_PROVIDER_MODEL"
        value = var.provider_model
      }

      env {
        name  = "MOD_PROVIDER_TIMEOUT_SECONDS"
        value = tostring(var.provider_timeout_seconds)
      }

      env {
        name  = "MOD_PROVIDER_CONCURRENCY"
        value = tostring(var.provider_concurrency)
      }

      env {
        name  = "MOD_PROVIDER_RATE_LIMIT_PER_MINUTE"
        value = tostring(var.provider_rate_limit_per_minute)
      }

      env {
        name  = "MOD_PROVIDER_MAX_ATTEMPTS"
        value = tostring(var.provider_max_attempts)
      }

      env {
        name  = "MOD_PROVIDER_RETRY_BASE_SECONDS"
        value = tostring(var.provider_retry_base_seconds)
      }

      env {
        name  = "MOD_PROVIDER_RETRY_MAX_SECONDS"
        value = tostring(var.provider_retry_max_seconds)
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 12

        http_get {
          path = "/health"
          port = 8080
        }
      }

      liveness_probe {
        timeout_seconds   = 3
        period_seconds    = 30
        failure_threshold = 3

        http_get {
          path = "/health"
          port = 8080
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.api_key_access,
    google_secret_manager_secret_iam_member.provider_key_access,
  ]
}

# Cloud Run performs network admission; FastAPI still requires X-API-Key on
# /moderate so the non-GCP Multiforum backend can call it safely.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count = var.allow_unauthenticated ? 1 : 0

  name     = google_cloud_run_v2_service.service.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
