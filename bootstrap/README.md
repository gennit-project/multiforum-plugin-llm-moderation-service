# Deployment bootstrap Terraform

This root owns the foundation required before the normal deployment Terraform
can run: bootstrap APIs, the versioned GCS state bucket, the GitHub deployer
identity and IAM grants, repository-scoped Workload Identity Federation, the
protected GitHub `production` environment, and non-secret Actions variables.
It also owns the sibling plugin repository's protected `release` environment,
so the same reviewer team must approve production deployment and publication.

Secret values are deliberately not Terraform inputs or resources. Terraform
state must never contain service credentials, smoke-identity credentials,
synthetic violation text, or the GitHub token used to dispatch central plugin
reconciliation.

## First apply

Terraform cannot create the bucket that already backs its own state. The small
`foundation/` root therefore creates only the prerequisite APIs and versioned
bucket with local state. Authenticate locally and apply it first:

```bash
gcloud auth application-default login
cp bootstrap/terraform.tfvars.example bootstrap/terraform.tfvars

terraform -chdir=bootstrap/foundation init
terraform -chdir=bootstrap/foundation plan \
  -var-file=../terraform.tfvars -out=foundation.tfplan
terraform -chdir=bootstrap/foundation apply foundation.tfplan
```

If the project has Service Usage disabled, enable that single prerequisite
before the first plan:

```bash
gcloud services enable serviceusage.googleapis.com --project YOUR_PROJECT_ID
```

Keep the small foundation state in an encrypted operator-controlled archive; it
contains no secrets. Then initialize the main bootstrap root directly against
the bucket and apply the reviewed identity/GitHub plan:

```bash
export GITHUB_TOKEN="a fine-grained token with administration access to the service and plugin repositories"
terraform -chdir=bootstrap init \
  -backend-config="bucket=YOUR_STATE_BUCKET" \
  -backend-config="prefix=llm-moderation/bootstrap"
terraform -chdir=bootstrap plan -out=bootstrap.tfplan
terraform -chdir=bootstrap apply bootstrap.tfplan
```

Future bootstrap plans use the same backend arguments. The deployment workflow
continues to use the separate `llm-moderation/production` prefix.

## Protected secrets

Set secret values directly in the GitHub environment after Terraform creates
it. These commands transmit values to GitHub but do not write them to Terraform
configuration or state:

```bash
gh secret set MOD_API_KEY --repo gennit-project/multiforum-plugin-llm-moderation-service --env production
gh secret set MOD_PROVIDER_API_KEY --repo gennit-project/multiforum-plugin-llm-moderation-service --env production
gh secret set MULTIFORUM_AUTOMATION_GITHUB_TOKEN --repo gennit-project/multiforum-plugin-llm-moderation-service --env production
gh secret set MULTIFORUM_OAUTH_CLIENT_SECRET --repo gennit-project/multiforum-plugin-llm-moderation-service --env production
gh secret set MULTIFORUM_SMOKE_LOGIN --repo gennit-project/multiforum-plugin-llm-moderation-service --env production
gh secret set MULTIFORUM_SMOKE_PASSWORD --repo gennit-project/multiforum-plugin-llm-moderation-service --env production
gh secret set MULTIFORUM_SMOKE_VIOLATION_TEXT --repo gennit-project/multiforum-plugin-llm-moderation-service --env production
```

The main bootstrap root manages every non-secret smoke-workflow variable from
`terraform.tfvars`. Keep `multiforum_smoke_forum` identical to the central
backend's `LLM_MODERATION_TRIAL_FORUM`; the smoke workflow deliberately offers
no forum input and therefore cannot be redirected to ordinary production data.
The four smoke values above are the only additional terminal-supplied secrets.
They are never placed in Terraform state or workflow output.

## Adopting existing resources

Before the first plan, import resources that were created by the former shell
bootstrap. Use the actual project, bucket, pool, provider, service-account, and
GitHub team IDs:

```bash
terraform -chdir=bootstrap/foundation import \
  -var-file=../terraform.tfvars google_storage_bucket.terraform_state YOUR_BUCKET
```

After the main bootstrap root is initialized against that bucket, import the
remaining existing resources:

```bash
terraform -chdir=bootstrap import google_service_account.deployer \
  projects/YOUR_PROJECT/serviceAccounts/llm-moderation-deployer@YOUR_PROJECT.iam.gserviceaccount.com
terraform -chdir=bootstrap import google_iam_workload_identity_pool.github \
  projects/YOUR_PROJECT_NUMBER/locations/global/workloadIdentityPools/github-actions
terraform -chdir=bootstrap import google_iam_workload_identity_pool_provider.repository \
  projects/YOUR_PROJECT_NUMBER/locations/global/workloadIdentityPools/github-actions/providers/llm-moderation-service
terraform -chdir=bootstrap import github_repository_environment.production \
  multiforum-plugin-llm-moderation-service:production
terraform -chdir=bootstrap import github_repository_environment.plugin_release \
  multiforum-plugin-llm-moderation:release
```

Import existing project IAM, bucket IAM, service-account IAM, API, and GitHub
variable resources reported by the first plan rather than allowing Terraform
to recreate or duplicate them. Import prerequisite API resources into the
foundation root. After import, require an empty or intentional reviewed plan
before apply.
