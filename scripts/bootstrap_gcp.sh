#!/usr/bin/env bash
# One-time bootstrap for resources required before Terraform can authenticate or
# store state. Safe to rerun after a partial setup.

set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID to the target Google Cloud project}"
: "${GITHUB_REPOSITORY:?Set GITHUB_REPOSITORY to owner/repository}"

GCP_REGION="${GCP_REGION:-us-central1}"
TF_STATE_BUCKET="${TF_STATE_BUCKET:-${GCP_PROJECT_ID}-multiforum-tfstate}"
DEPLOY_SERVICE_ACCOUNT="${DEPLOY_SERVICE_ACCOUNT:-llm-moderation-deployer}"
WORKLOAD_IDENTITY_POOL="${WORKLOAD_IDENTITY_POOL:-github-actions}"
WORKLOAD_IDENTITY_PROVIDER="${WORKLOAD_IDENTITY_PROVIDER:-llm-moderation-service}"

for command in gcloud gh; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "Required command is not installed: ${command}" >&2
    exit 1
  fi
done

gcloud config set project "${GCP_PROJECT_ID}"
gcloud services enable cloudresourcemanager.googleapis.com iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com storage.googleapis.com serviceusage.googleapis.com

if ! gcloud storage buckets describe "gs://${TF_STATE_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${TF_STATE_BUCKET}" --location="${GCP_REGION}" --uniform-bucket-level-access
  gcloud storage buckets update "gs://${TF_STATE_BUCKET}" --versioning
fi

deploy_email="${DEPLOY_SERVICE_ACCOUNT}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "${deploy_email}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${DEPLOY_SERVICE_ACCOUNT}" --display-name="LLM moderation GitHub deployer"
fi

for attempt in {1..12}; do
  if gcloud iam service-accounts describe "${deploy_email}" >/dev/null 2>&1; then
    break
  fi
  if (( attempt == 12 )); then
    echo "Service account did not become available: ${deploy_email}" >&2
    exit 1
  fi
  echo "Waiting for service account propagation (${attempt}/12)..."
  sleep 5
done

project_roles=(
  roles/artifactregistry.admin
  roles/iam.serviceAccountAdmin
  roles/iam.serviceAccountUser
  roles/run.admin
  roles/secretmanager.admin
  roles/serviceusage.serviceUsageAdmin
)
for role in "${project_roles[@]}"; do
  gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" --member="serviceAccount:${deploy_email}" --role="${role}" --condition=None --quiet >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://${TF_STATE_BUCKET}" --member="serviceAccount:${deploy_email}" --role=roles/storage.objectAdmin --quiet >/dev/null

if ! gcloud iam workload-identity-pools describe "${WORKLOAD_IDENTITY_POOL}" --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "${WORKLOAD_IDENTITY_POOL}" --location=global --display-name="GitHub Actions"
fi

if ! gcloud iam workload-identity-pools providers describe "${WORKLOAD_IDENTITY_PROVIDER}" --workload-identity-pool="${WORKLOAD_IDENTITY_POOL}" --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "${WORKLOAD_IDENTITY_PROVIDER}" --workload-identity-pool="${WORKLOAD_IDENTITY_POOL}" --location=global --issuer-uri="https://token.actions.githubusercontent.com" --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" --attribute-condition="assertion.repository=='${GITHUB_REPOSITORY}'" --display-name="LLM moderation service GitHub repository"
fi

project_number="$(gcloud projects describe "${GCP_PROJECT_ID}" --format='value(projectNumber)')"
principal="principalSet://iam.googleapis.com/projects/${project_number}/locations/global/workloadIdentityPools/${WORKLOAD_IDENTITY_POOL}/attribute.repository/${GITHUB_REPOSITORY}"
gcloud iam service-accounts add-iam-policy-binding "${deploy_email}" --role=roles/iam.workloadIdentityUser --member="${principal}" --quiet >/dev/null

provider_name="projects/${project_number}/locations/global/workloadIdentityPools/${WORKLOAD_IDENTITY_POOL}/providers/${WORKLOAD_IDENTITY_PROVIDER}"
gh variable set GCP_PROJECT_ID --repo "${GITHUB_REPOSITORY}" --body "${GCP_PROJECT_ID}"
gh variable set GCP_REGION --repo "${GITHUB_REPOSITORY}" --body "${GCP_REGION}"
gh variable set TF_STATE_BUCKET --repo "${GITHUB_REPOSITORY}" --body "${TF_STATE_BUCKET}"
gh variable set GCP_DEPLOY_SERVICE_ACCOUNT --repo "${GITHUB_REPOSITORY}" --body "${deploy_email}"
gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --repo "${GITHUB_REPOSITORY}" --body "${provider_name}"

cat <<EOF

Bootstrap complete.

GitHub repository variables now point to:
  project: ${GCP_PROJECT_ID}
  region: ${GCP_REGION}
  state bucket: ${TF_STATE_BUCKET}
  deploy identity: ${deploy_email}

Still required in the GitHub production environment:
  secrets.MOD_API_KEY
  secrets.MOD_PROVIDER_API_KEY
  secrets.MULTIFORUM_AUTOMATION_GITHUB_TOKEN

Keep a secure copy of MOD_API_KEY. The backend repository's central production
plugin workflow must use the same shared secret.
EOF
