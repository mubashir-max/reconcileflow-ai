"""Validated environment-based API configuration."""

from __future__ import annotations

from enum import StrEnum
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class APISettings(BaseSettings):
    """Runtime settings loaded from `RECONCILEFLOW_*` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="RECONCILEFLOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    app_name: str = Field(default="ReconcileFlow AI", min_length=1, max_length=100)
    app_version: str = Field(default_factory=lambda: version("reconcileflow-ai"), min_length=1)
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    api_prefix: str = "/api/v1"
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    database_url: SecretStr = SecretStr("sqlite+pysqlite:///:memory:")
    database_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=200)
    database_pool_timeout_seconds: int = Field(default=30, ge=1, le=300)
    upload_directory: Path = Path("var/uploads")
    max_upload_size_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value().strip()
        if not url.startswith(("postgresql+psycopg://", "sqlite+pysqlite://")):
            raise ValueError("database_url must use postgresql+psycopg or sqlite+pysqlite")
        return SecretStr(url)

    @field_validator("app_name", "app_version")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/"):
            raise ValueError("api_prefix must start with '/'")
        if value == "/" or value.endswith("/"):
            raise ValueError("api_prefix must be a non-root path without a trailing slash")
        return value

    @field_validator("upload_directory")
    @classmethod
    def validate_upload_directory(cls, value: Path) -> Path:
        if not str(value).strip():
            raise ValueError("upload_directory must not be blank")
        return value
