"""Validated environment-based API configuration."""

from __future__ import annotations

from enum import StrEnum
from importlib.metadata import version
from typing import Literal

from pydantic import Field, field_validator
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
