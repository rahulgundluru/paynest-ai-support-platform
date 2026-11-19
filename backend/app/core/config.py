"""Application settings, loaded from environment variables (never from source code)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"

    database_url: SecretStr = Field(description="postgresql+asyncpg://user:pass@host:port/db")
    db_pool_size: int = 5
    db_max_overflow: int = 5

    jwt_secret: SecretStr = Field(description="HS256 signing secret, at least 32 characters")
    jwt_ttl_minutes: int = 480
    cookie_name: str = "paynest_session"
    cookie_secure: bool = True

    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("jwt_secret")
    @classmethod
    def _secret_strength(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
