output "service_url" {
  description = "HTTPS URL of the deployed Cloud Run service."
  value       = google_cloud_run_v2_service.service.uri
}

output "image_repository" {
  description = "Artifact Registry repository prefix for service images."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}

output "api_key_secret_id" {
  value = google_secret_manager_secret.api_key.secret_id
}

output "provider_api_key_secret_id" {
  value = google_secret_manager_secret.provider_api_key.secret_id
}
