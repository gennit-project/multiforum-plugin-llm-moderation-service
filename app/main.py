import json
import logging
import re
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status

from .config import Settings, get_settings
from .models import HealthResponse, ModerationRequest, ModerationResponse
from .provider import ModerationProvider, OpenAICompatibleProvider, ProviderError, ProviderGate
from .security import require_api_key

logger = logging.getLogger(__name__)
CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@asynccontextmanager
async def lifespan(application: FastAPI):
    async with httpx.AsyncClient() as client:
        application.state.provider_client = client
        application.state.provider_gates = {}
        yield


app = FastAPI(title="Multiforum LLM Moderation Service", version="0.2.0", lifespan=lifespan)


def get_provider(
    request: Request, settings: Settings = Depends(get_settings)
) -> ModerationProvider:
    gate_key = (settings.provider_concurrency, settings.provider_rate_limit_per_minute)
    gates: dict[tuple[int, int], ProviderGate] = request.app.state.provider_gates
    gate = gates.setdefault(
        gate_key,
        ProviderGate(
            concurrency=settings.provider_concurrency,
            rate_limit_per_minute=settings.provider_rate_limit_per_minute,
        ),
    )
    return OpenAICompatibleProvider(settings, request.app.state.provider_client, gate)


@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", providerModel=settings.provider_model)


@app.post(
    "/moderate",
    response_model=ModerationResponse,
    dependencies=[Depends(require_api_key)],
)
async def moderate(
    request: ModerationRequest,
    response: Response,
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    provider: ModerationProvider = Depends(get_provider),
) -> ModerationResponse:
    if x_correlation_id and not CORRELATION_ID.fullmatch(x_correlation_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid correlation ID"
        )
    correlation_id = x_correlation_id or str(uuid4())
    response.headers["X-Correlation-ID"] = correlation_id
    logger.info(json.dumps({"event": "moderation_started", "correlation_id": correlation_id}))
    try:
        verdict = await provider.moderate(request)
    except ProviderError as exc:
        logger.warning(
            json.dumps(
                {
                    "event": "moderation_failed",
                    "correlation_id": correlation_id,
                    "error_type": type(exc).__name__,
                }
            )
        )
        headers = {"X-Correlation-ID": correlation_id}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=headers) from exc
    logger.info(
        json.dumps(
            {
                "event": "moderation_completed",
                "correlation_id": correlation_id,
                "violation_count": len(verdict.violations),
            }
        )
    )
    return verdict
