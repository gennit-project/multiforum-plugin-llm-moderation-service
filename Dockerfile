# Cloud Run-compatible container for the LLM moderation service.
# Single-stage: the app is pure Python with no build step.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so the layer is cached across code changes.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

# Cloud Run sets $PORT (default 8080) and expects the app to listen on it.
ENV PORT=8080
EXPOSE 8080

# Run as a non-root user.
RUN useradd --create-home --uid 1001 appuser
USER appuser

# `sh -c` so $PORT is expanded at runtime.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
