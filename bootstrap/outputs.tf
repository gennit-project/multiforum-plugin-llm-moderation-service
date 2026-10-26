output "state_bucket" {
  value = var.state_bucket_name
}

output "deploy_service_account" {
  value = google_service_account.deployer.email
}

output "workload_identity_provider" {
  value = google_iam_workload_identity_pool_provider.repository.name
}
