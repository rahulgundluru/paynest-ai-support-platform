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

    # Fernet key (urlsafe base64, 32 bytes) for the PII vault and raw source records.
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    pii_vault_key: SecretStr = Field(description="Encryption key for PII vault and raw records")
    # Retention for vault values and raw records. ASSUMPTION pending the DPO's retention decision.
    pii_retention_days: int = 365

    # Model providers. "none" = no model configured: AI steps record `unavailable` and route to people.
    llm_provider: Literal["none", "bedrock", "openrouter"] = "none"
    embedding_provider: Literal["none", "bedrock"] = "none"
    # OpenRouter (OpenAI-compatible gateway). The key comes from the environment only; it is never stored
    # in the database, logged or returned by the API. Models, caps and the on/off switch are runtime
    # settings (AI management). Approved for the synthetic case data only (data_collection=deny, zdr).
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = 45.0
    bedrock_region: str = "ap-south-1"
    bedrock_classifier_model_id: str | None = None  # confirm id + in-region availability before use
    bedrock_embedding_model_id: str | None = None
    embedding_dimensions: int = 1024
    classification_confidence_threshold: float = 0.80
    # Optional price configuration for cost tracking (USD per 1M tokens). Unset = cost not estimated.
    classifier_input_usd_per_mtok: float | None = None
    classifier_output_usd_per_mtok: float | None = None

    # Read-only mirror of the upstream case repository (see scripts/source_data.py).
    data_source_dir: str = Field(default="../data/source")

    @field_validator("jwt_secret")
    @classmethod
    def _secret_strength(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
