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

## API

- `GET /health` is unauthenticated.
- `POST /moderate` requires `X-API-Key` and accepts an optional
  `X-Correlation-ID` header.

Provider credentials are service environment variables and are never sent to
or stored by the Multiforum backend.
