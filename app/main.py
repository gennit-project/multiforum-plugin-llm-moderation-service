import json
import logging
import re
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status

from .config import Settings, get_settings
from .models import HealthResponse, ModerationRequest, ModerationResponse
from .provider import ModerationProvider, OpenAICompatibleProvider, ProviderError
from .security import require_api_key

logger = logging.getLogger(__name__)
app = FastAPI(title="Multiforum LLM Moderation Service", version="0.1.0")
CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def get_provider(settings: Settings = Depends(get_settings)) -> ModerationProvider:
    return OpenAICompatibleProvider(settings)


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
        logger.warning(json.dumps({"event": "moderation_failed", "correlation_id": correlation_id}))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
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
