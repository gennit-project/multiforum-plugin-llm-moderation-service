from fastapi import Request

from app.config import Settings
from app.main import app, get_provider
from app.models import ModerationResponse
from app.provider import (
    OpenAICompatibleProvider,
    ProviderCapacityError,
    ProviderConfigurationError,
    ProviderTransientError,
)

REQUEST = {
    "content": {"type": "comment", "id": "comment-1", "body": "Buy this now"},
    "rules": [{"scope": "server", "id": "server:0", "text": "No spam"}],
    "policy": {"temperature": 0, "maxTokens": 300},
}


def test_health_is_public(client):
    response = client.get("/health")
    assert response.json() == {"status": "ok", "providerModel": "gpt-4o-mini"}


def test_provider_dependency_reuses_application_client_and_gate(client, settings: Settings):
    request = Request({"type": "http", "app": app})

    first = get_provider(request, settings)
    second = get_provider(request, settings)

    assert isinstance(first, OpenAICompatibleProvider)
    assert isinstance(second, OpenAICompatibleProvider)
    assert first.client is second.client
    assert first.gate is second.gate


def test_moderate_requires_api_key(client):
    response = client.post("/moderate", json=REQUEST)
    assert response.status_code == 401


def test_moderate_returns_structured_verdict(client, override_provider):
    provider = override_provider(
        ModerationResponse.model_validate(
            {
                "violations": [{"scope": "server", "ruleId": "server:0"}],
                "recommendation": "remove",
                "confidence": 0.93,
                "rationale": "Promotional spam",
            }
        )
    )
    response = client.post(
        "/moderate",
        headers={"X-API-Key": "service-secret-123", "X-Correlation-ID": "run-123"},
        json=REQUEST,
    )
    assert response.json() == {
        "violations": [{"scope": "server", "ruleId": "server:0"}],
        "recommendation": "remove",
        "confidence": 0.93,
        "rationale": "Promotional spam",
    }
    assert response.headers["x-correlation-id"] == "run-123"
    assert provider.requests[0].content.id == "comment-1"


def test_moderate_rejects_duplicate_rule_keys(client):
    request = {**REQUEST, "rules": [REQUEST["rules"][0], REQUEST["rules"][0]]}
    response = client.post("/moderate", headers={"X-API-Key": "service-secret-123"}, json=request)
    assert response.status_code == 422


def test_moderate_rejects_log_unsafe_correlation_id(client, override_provider):
    override_provider(
        ModerationResponse(
            violations=[], recommendation="none", confidence=0, rationale="No violation"
        )
    )
    response = client.post(
        "/moderate",
        headers={"X-API-Key": "service-secret-123", "X-Correlation-ID": "bad\nvalue"},
        json=REQUEST,
    )
    assert response.status_code == 400


def test_moderate_returns_retryable_capacity_errors_with_correlation_id(client, override_provider):
    override_provider(ProviderCapacityError("Provider is busy", retry_after=17))

    response = client.post(
        "/moderate",
        headers={"X-API-Key": "service-secret-123", "X-Correlation-ID": "run-429"},
        json=REQUEST,
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    assert response.headers["x-correlation-id"] == "run-429"
    assert response.json() == {"detail": "Provider is busy"}


def test_moderate_distinguishes_transient_and_configuration_failures(client, override_provider):
    override_provider(ProviderTransientError("Provider unavailable"))
    transient = client.post("/moderate", headers={"X-API-Key": "service-secret-123"}, json=REQUEST)

    override_provider(ProviderConfigurationError("Provider authentication failed"))
    configuration = client.post(
        "/moderate", headers={"X-API-Key": "service-secret-123"}, json=REQUEST
    )

    assert transient.status_code == 503
    assert configuration.status_code == 424
