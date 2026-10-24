import json
from collections.abc import Awaitable, Callable

import httpx
import pytest

from app.config import Settings
from app.models import ModerationRequest
from app.provider import (
    OpenAICompatibleProvider,
    ProviderCapacityError,
    ProviderConfigurationError,
    ProviderError,
    ProviderGate,
    ProviderTransientError,
)


def request() -> ModerationRequest:
    return ModerationRequest.model_validate(
        {
            "content": {"type": "comment", "id": "c-1", "body": "hello"},
            "rules": [{"scope": "server", "id": "server:0", "text": "Be kind"}],
        }
    )


def service_settings(**overrides) -> Settings:
    return Settings(
        api_key="service-secret-123",
        provider_api_key="provider-key",
        provider_retry_base_seconds=0.1,
        provider_retry_max_seconds=5,
        **overrides,
    )


def provider(
    settings: Settings,
    client: httpx.AsyncClient,
    *,
    gate: ProviderGate | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> OpenAICompatibleProvider:
    kwargs = {"sleep": sleep} if sleep is not None else {}
    return OpenAICompatibleProvider(
        settings,
        client,
        gate or ProviderGate(100, 10_000),
        **kwargs,
    )


def success_response() -> httpx.Response:
    verdict = {
        "violations": [],
        "recommendation": "none",
        "confidence": 0.1,
        "rationale": "No violation",
    }
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(verdict)}}]})


@pytest.mark.asyncio
async def test_provider_sends_content_as_json_data():
    seen: dict = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(http_request.content))
        return success_response()

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    moderation_provider = provider(service_settings(), client)

    result = await moderation_provider.moderate(request())

    assert result.recommendation == "none"
    assert json.loads(seen["messages"][1]["content"])["content"]["id"] == "c-1"
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_converts_invalid_output_to_provider_error():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"choices": []}))
    )
    moderation_provider = provider(service_settings(), client)

    with pytest.raises(ProviderError):
        await moderation_provider.moderate(request())
    await client.aclose()


@pytest.mark.asyncio
async def test_gate_rejects_excess_concurrency_without_waiting():
    gate = ProviderGate(concurrency=1, rate_limit_per_minute=10)

    async with gate.admit():
        with pytest.raises(ProviderCapacityError) as raised:
            async with gate.admit():
                pass

    assert raised.value.retry_after == 1


@pytest.mark.asyncio
async def test_gate_enforces_a_rolling_minute_limit():
    now = [100.0]
    gate = ProviderGate(
        concurrency=2,
        rate_limit_per_minute=2,
        clock=lambda: now[0],
    )

    async with gate.admit():
        pass
    now[0] = 101
    async with gate.admit():
        pass

    with pytest.raises(ProviderCapacityError) as raised:
        async with gate.admit():
            pass
    assert raised.value.retry_after == 59

    now[0] = 160
    async with gate.admit():
        pass


@pytest.mark.asyncio
async def test_provider_retries_transient_failures_with_bounded_backoff():
    statuses = iter([500, 503, 200])
    attempts = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        status = next(statuses)
        return httpx.Response(status) if status != 200 else success_response()

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    moderation_provider = provider(service_settings(), client, sleep=record_sleep)

    result = await moderation_provider.moderate(request())

    assert result.recommendation == "none"
    assert attempts == 3
    assert sleeps == [0.1, 0.2]
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_honors_retry_after_for_rate_limits():
    attempts = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return success_response()

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    moderation_provider = provider(service_settings(), client, sleep=record_sleep)

    await moderation_provider.moderate(request())

    assert attempts == 2
    assert sleeps == [2]
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_returns_long_retry_after_to_the_caller():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(429, headers={"Retry-After": "60"})
        )
    )
    moderation_provider = provider(service_settings(), client)

    with pytest.raises(ProviderCapacityError) as raised:
        await moderation_provider.moderate(request())

    assert raised.value.retry_after == 60
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_does_not_retry_authentication_failures():
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, text="secret details must not escape")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    moderation_provider = provider(service_settings(), client)

    with pytest.raises(ProviderConfigurationError) as raised:
        await moderation_provider.moderate(request())

    assert attempts == 1
    assert "secret details" not in str(raised.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_marks_exhausted_transport_failures_as_transient():
    attempts = 0
    sleeps: list[float] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("connection failed", request=http_request)

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    moderation_provider = provider(
        service_settings(provider_max_attempts=2), client, sleep=record_sleep
    )

    with pytest.raises(ProviderTransientError):
        await moderation_provider.moderate(request())

    assert attempts == 2
    assert sleeps == [0.1]
    await client.aclose()
