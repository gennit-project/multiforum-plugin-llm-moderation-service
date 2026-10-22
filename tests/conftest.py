from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, get_provider
from app.models import ModerationRequest, ModerationResponse


class FakeProvider:
    def __init__(self, response: ModerationResponse):
        self.response = response
        self.requests: list[ModerationRequest] = []

    async def moderate(self, request: ModerationRequest) -> ModerationResponse:
        self.requests.append(request)
        return self.response


@pytest.fixture
def settings() -> Settings:
    return Settings(api_key="service-secret-123", provider_api_key="provider-key")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def override_provider():
    providers: list[FakeProvider] = []

    def apply(response: ModerationResponse) -> FakeProvider:
        provider = FakeProvider(response)
        providers.append(provider)
        app.dependency_overrides[get_provider] = lambda: provider
        return provider

    yield apply
    app.dependency_overrides.pop(get_provider, None)
