import json

import httpx
import pytest

from app.config import Settings
from app.models import ModerationRequest
from app.provider import OpenAICompatibleProvider, ProviderError


def request() -> ModerationRequest:
    return ModerationRequest.model_validate(
        {
            "content": {"type": "comment", "id": "c-1", "body": "hello"},
            "rules": [{"scope": "server", "id": "server:0", "text": "Be kind"}],
        }
    )


@pytest.mark.asyncio
async def test_provider_sends_content_as_json_data():
    seen: dict = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(http_request.content))
        verdict = {
            "violations": [],
            "recommendation": "none",
            "confidence": 0.1,
            "rationale": "No violation",
        }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(verdict)}}]}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(api_key="service-secret-123", provider_api_key="provider-key")
    provider = OpenAICompatibleProvider(settings, client)

    result = await provider.moderate(request())

    assert result.recommendation == "none"
    assert json.loads(seen["messages"][1]["content"])["content"]["id"] == "c-1"
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_converts_invalid_output_to_provider_error():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"choices": []}))
    )
    settings = Settings(api_key="service-secret-123", provider_api_key="provider-key")
    provider = OpenAICompatibleProvider(settings, client)

    with pytest.raises(ProviderError):
        await provider.moderate(request())
    await client.aclose()
