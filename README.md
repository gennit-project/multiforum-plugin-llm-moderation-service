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
