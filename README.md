# Multiforum LLM Moderation Service

External FastAPI service for the experimental Multiforum LLM moderation plugin.
It receives content plus canonical rules, asks an LLM for a structured verdict,
and returns rule identifiers only. The Multiforum backend remains responsible
for validating citations and creating reports.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export MOD_API_KEY=local-service-key
export MOD_PROVIDER_API_KEY=your-provider-key
uvicorn app.main:app --reload
```

Run checks with `ruff check .` and `pytest --cov=app --cov-fail-under=80`.

## Configuration

All settings use the `MOD_` environment-variable prefix.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MOD_API_KEY` | required | Shared secret accepted in the plugin's `X-API-Key` header. Must contain at least 16 characters. |
| `MOD_PROVIDER_API_KEY` | required | Credential sent only to the configured LLM provider. |
| `MOD_PROVIDER_BASE_URL` | `https://api.openai.com/v1` | Base URL for an OpenAI-compatible API. |
| `MOD_PROVIDER_MODEL` | `gpt-4o-mini` | Model used when the plugin request does not override it. |
| `MOD_PROVIDER_TIMEOUT_SECONDS` | `30` | Timeout for one provider attempt. |
| `MOD_PROVIDER_CONCURRENCY` | `2` | Maximum provider calls in flight in one service instance. |
| `MOD_PROVIDER_RATE_LIMIT_PER_MINUTE` | `30` | Rolling limit on provider call starts per service instance, including retries. |
| `MOD_PROVIDER_MAX_ATTEMPTS` | `3` | Maximum attempts for a transient provider failure. |
| `MOD_PROVIDER_RETRY_BASE_SECONDS` | `0.25` | Initial exponential retry delay. |
| `MOD_PROVIDER_RETRY_MAX_SECONDS` | `5` | Maximum delay held inside a service request. |

Provider timeouts, connection failures, `429` responses, and `5xx` responses
are retried with bounded exponential backoff. A provider `Retry-After` value is
honored when it is within the configured maximum; longer delays are returned to
the plugin so its durable queue can retry later. Provider authentication and
request-configuration failures are not retried.

## API

- `GET /health` is unauthenticated.
- `POST /moderate` requires `X-API-Key` and accepts an optional
  `X-Correlation-ID` header.

The service returns `429` with `Retry-After` when its local provider gate or the
upstream provider is rate limited, `503` for exhausted transient failures, and
`424` for non-retryable provider configuration failures. Correlation IDs are
included in both successful and provider-error responses.

Provider credentials are service environment variables and are never sent to
or stored by the Multiforum backend.

## Cloud Run deployment

Deployment is intentionally manual. Merging code does not modify GCP or deploy
a revision. The production workflow uses Workload Identity Federation, builds
an immutable commit-tagged image, applies Terraform, and verifies health plus
API-key enforcement. A provider-backed smoke request is optional and disabled
by default to avoid an unexpected model charge.

### One-time bootstrap

An operator with permission to administer the target GCP project and repository
runs:

```bash
export GCP_PROJECT_ID=your-project-id
export GITHUB_REPOSITORY=gennit-project/multiforum-plugin-llm-moderation-service
bash scripts/bootstrap_gcp.sh
```

The bootstrap creates or reuses the Terraform state bucket, a dedicated deploy
service account, and a repository-specific Workload Identity provider. It also
sets these repository variables:

- `GCP_PROJECT_ID`
- `GCP_REGION`
- `TF_STATE_BUCKET`
- `GCP_DEPLOY_SERVICE_ACCOUNT`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`

Configure the following secrets in the repository's protected `production`
environment before the first deployment:

- `MOD_API_KEY`: a randomly generated shared key of at least 32 characters
- `MOD_PROVIDER_API_KEY`: the external LLM provider credential
- `MULTIFORUM_AUTOMATION_GITHUB_TOKEN`: a fine-grained token limited to Actions
  write access on `gennit-project/multiforum-backend`, used only to dispatch the
  central production plugin reconciliation workflow

Configure the identical `MOD_API_KEY` in the backend repository's protected
`production` environment. Configure its central workflow variables, including
an explicit `LLM_MODERATION_TRIAL_FORUM`; the first rollout remains allowlist
only. The provider key stays exclusively in this service repository.

The workflow also accepts optional repository variables corresponding to the
non-secret `MOD_PROVIDER_*` settings in the configuration table. Defaults match
the application defaults.

### Deployment and verification

Run the `Deploy LLM moderation service` workflow manually from the intended
commit or tag. The workflow:

1. validates required variables and secrets;
2. creates the Artifact Registry repository and secret containers when needed;
3. uploads new secret versions without storing plaintext in Terraform state;
4. builds and pushes an image tagged with the commit SHA;
5. applies the reviewed Terraform plan;
6. verifies `/health` and confirms `/moderate` rejects missing credentials.
7. dispatches the central Multiforum reconciliation with the Terraform service
   URL; that reviewed workflow installs/enables v0.7.0 and owns all four LLM
   event pipelines without replacing unrelated topology.

Enable `run_live_moderation` only when one real provider request is desired.
The check validates the structured response but does not require a particular
moderation recommendation.

The experimental configuration defaults to scale-to-zero with one maximum
instance. This makes the in-process provider rate limit a service-wide ceiling.
Increasing `max_instance_count` multiplies the effective provider concurrency
and per-minute limits and should be paired with a distributed limiter or a
deliberate provider-capacity review.

### Secret rotation and rollback

Rotate either credential by updating the matching GitHub production secret and
dispatching the deployment workflow again. The workflow creates a new Secret
Manager version and forces a new Cloud Run revision.

To roll back, dispatch the workflow from the previously reviewed commit or tag.
Images are immutable and tagged by commit SHA, so the selected source revision
determines the exact image and infrastructure definition restored by Terraform.

Terraform state uses the `llm-moderation/production` prefix in the configured
GCS bucket. Terraform owns secret containers and IAM bindings, but never secret
values.
