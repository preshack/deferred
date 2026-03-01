"""Deferred API — Configuration module.

Loads all settings from environment variables with Pydantic validation.
"""

from __future__ import annotations

import json
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://deferred:deferred_secret@localhost:5432/deferred_db"
    DATABASE_URL_SYNC: str = "postgresql://deferred:deferred_secret@localhost:5432/deferred_db"

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- RabbitMQ ---
    RABBITMQ_URL: str = "amqp://deferred:deferred_secret@localhost:5672/"

    # --- JWT / Auth ---
    JWT_SECRET_KEY: str = "CHANGE_ME_TO_A_RANDOM_64_CHAR_HEX_STRING"
    JWT_ALGORITHM: str = "HS256"  # Fallback; EdDSA used when keys available
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Crypto ---
    MASTER_ISSUER_SEED: str = "CHANGE_ME_TO_A_RANDOM_64_CHAR_HEX_STRING"
    ARGON2_MEMORY_KB: int = 65536
    ARGON2_ITERATIONS: int = 3
    ARGON2_PARALLELISM: int = 4

    # --- API ---
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_DEBUG: bool = True
    API_TITLE: str = "Deferred API"
    API_VERSION: str = "1.0.0"
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    # --- Observability ---
    LOG_LEVEL: str = "INFO"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    OTEL_SERVICE_NAME: str = "deferred-api"
    PROMETHEUS_ENABLED: bool = True

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list) -> list:
        if isinstance(v, str):
            return json.loads(v)
        return v

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


# Singleton instance
settings = Settings()
