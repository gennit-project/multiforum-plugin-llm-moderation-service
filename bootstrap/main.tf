locals {
  repository_full_name = "${var.github_owner}/${var.github_repository}"
  deploy_member        = "serviceAccount:${google_service_account.deployer.email}"
  bootstrap_services = toset([
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "serviceusage.googleapis.com",
    "sts.googleapis.com",
    "storage.googleapis.com",
  ])
  deploy_project_roles = toset([
    "roles/artifactregistry.admin",
    "roles/iam.serviceAccountAdmin",
    "roles/iam.serviceAccountUser",
    "roles/run.admin",
    "roles/secretmanager.admin",
    "roles/serviceusage.serviceUsageAdmin",
  ])
  smoke_actions_variables = {
    MULTIFORUM_GRAPHQL_URL           = var.multiforum_graphql_url
    MULTIFORUM_OAUTH_TOKEN_URL       = var.multiforum_oauth_token_url
    MULTIFORUM_OAUTH_CLIENT_ID       = var.multiforum_oauth_client_id
    MULTIFORUM_OAUTH_AUDIENCE        = var.multiforum_oauth_audience
    MULTIFORUM_OAUTH_REALM           = var.multiforum_oauth_realm
    MULTIFORUM_SMOKE_FORUM           = var.multiforum_smoke_forum
    MULTIFORUM_SMOKE_AUTHOR_USERNAME = var.multiforum_smoke_author_username
    MULTIFORUM_SMOKE_EXPECTED_RULE   = var.multiforum_smoke_expected_rule
  }
}

resource "google_project_service" "bootstrap" {
  for_each = local.bootstrap_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "deployer" {
  account_id   = var.deploy_service_account_id
  display_name = "LLM moderation GitHub deployer"

  depends_on = [google_project_service.bootstrap]
}

resource "google_project_iam_member" "deployer" {
  for_each = local.deploy_project_roles

  project = var.project_id
  role    = each.value
  member  = local.deploy_member
}

resource "google_storage_bucket_iam_member" "deployer_state" {
  bucket = var.state_bucket_name
  role   = "roles/storage.objectAdmin"
  member = local.deploy_member
}

resource "google_storage_bucket_iam_member" "deployer_bucket_reader" {
  bucket = var.state_bucket_name
  role   = "roles/storage.legacyBucketReader"
  member = local.deploy_member
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = var.workload_identity_pool_id
  display_name              = "GitHub Actions"

  depends_on = [google_project_service.bootstrap]
}

resource "google_iam_workload_identity_pool_provider" "repository" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = var.workload_identity_provider_id
  display_name                       = "LLM moderation service GitHub repository"
  attribute_condition                = "assertion.repository == '${local.repository_full_name}'"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_impersonation" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${local.repository_full_name}"
}

resource "github_repository_environment" "production" {
  repository  = var.github_repository
  environment = "production"

  reviewers {
    teams = var.production_reviewer_team_ids
  }

  deployment_branch_policy {
    protected_branches     = true
    custom_branch_policies = false
  }
}

resource "github_actions_variable" "project_id" {
  repository    = var.github_repository
  variable_name = "GCP_PROJECT_ID"
  value         = var.project_id
}

resource "github_actions_variable" "region" {
  repository    = var.github_repository
  variable_name = "GCP_REGION"
  value         = var.region
}

resource "github_actions_variable" "state_bucket" {
  repository    = var.github_repository
  variable_name = "TF_STATE_BUCKET"
  value         = var.state_bucket_name
}

resource "github_actions_variable" "deploy_service_account" {
  repository    = var.github_repository
  variable_name = "GCP_DEPLOY_SERVICE_ACCOUNT"
  value         = google_service_account.deployer.email
}

resource "github_actions_variable" "workload_identity_provider" {
  repository    = var.github_repository
  variable_name = "GCP_WORKLOAD_IDENTITY_PROVIDER"
  value         = google_iam_workload_identity_pool_provider.repository.name
}

resource "github_actions_variable" "smoke" {
  for_each = local.smoke_actions_variables

  repository    = var.github_repository
  variable_name = each.key
  value         = each.value
}
