from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOD_", extra="ignore")

    api_key: str = Field(min_length=16)
    provider_api_key: str = Field(min_length=1)
    provider_base_url: str = "https://api.openai.com/v1"
    provider_model: str = "gpt-4o-mini"
    provider_timeout_seconds: float = Field(default=30.0, gt=0, le=120)


@lru_cache
def get_settings() -> Settings:
    return Settings()
