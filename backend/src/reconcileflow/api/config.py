"""Validated environment-based API configuration."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from importlib.metadata import version
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
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
    storage_provider: str = "local"
    s3_endpoint_url: str | None = None
    s3_region: str = Field(default="us-east-1", min_length=1, max_length=100)
    s3_bucket: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_use_path_style: bool = False
    s3_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    s3_read_timeout_seconds: int = Field(default=30, ge=1, le=300)
    s3_auto_create_bucket: bool = False
    presigned_url_ttl_seconds: int = Field(default=300, ge=60, le=900)
    abandoned_upload_retention_hours: int = Field(default=24, ge=1, le=720)
    storage_integrity_grace_hours: int = Field(default=24, ge=1, le=720)
    storage_integrity_batch_size: int = Field(default=500, ge=1, le=10000)
    max_upload_size_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)
    default_organization_storage_quota_bytes: int = Field(default=10 * 1024 * 1024 * 1024, ge=0)
    token_signing_secret: SecretStr = SecretStr("development-only-change-this-token-secret")
    token_issuer: str = Field(default="reconcileflow-api", min_length=1, max_length=200)
    token_audience: str = Field(default="reconcileflow-clients", min_length=1, max_length=200)
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)
    login_max_failed_attempts: int = Field(default=5, ge=2, le=20)
    login_lockout_minutes: int = Field(default=15, ge=1, le=1440)
    worker_id: str = Field(default="reconcileflow-worker", min_length=1, max_length=200)
    worker_poll_interval_seconds: float = Field(default=2.0, ge=0.1, le=60.0)
    worker_stale_timeout_seconds: int = Field(default=300, ge=30, le=86400)
    worker_retry_delay_seconds: int = Field(default=30, ge=1, le=86400)
    max_manual_job_retries: int = Field(default=3, ge=1, le=20)
    worker_health_stale_seconds: int = Field(default=120, ge=30, le=86400)
    succeeded_job_retention_days: int = Field(default=30, ge=1, le=3650)
    failed_job_retention_days: int = Field(default=90, ge=1, le=3650)
    cancelled_job_retention_days: int = Field(default=30, ge=1, le=3650)
    worker_record_retention_days: int = Field(default=7, ge=1, le=3650)
    cleanup_batch_size: int = Field(default=500, ge=1, le=10000)
    default_job_timeout_seconds: int = Field(default=900, ge=30, le=86400)
    maximum_job_timeout_seconds: int = Field(default=3600, ge=30, le=86400)
    job_priority_aging_seconds: int = Field(default=300, ge=30, le=86400)
    ai_inference_provider: str = "disabled"
    ai_model_version: str = Field(default="deterministic-v1", min_length=1, max_length=100)
    ai_prompt_version: str = Field(default="match-suggestion-v1", min_length=1, max_length=100)
    ai_inference_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0)
    ai_max_candidates_per_request: int = Field(default=100, ge=1, le=1000)
    ai_max_suggestions_per_response: int = Field(default=20, ge=1, le=100)
    ai_candidate_max_date_difference_days: int = Field(default=30, ge=0, le=365)
    ai_candidate_max_amount_difference_ratio: Decimal = Field(
        default=Decimal("0.25"), ge=Decimal("0"), le=Decimal("1")
    )

    @model_validator(mode="after")
    def validate_token_security(self) -> APISettings:
        secret = self.token_signing_secret.get_secret_value()
        if len(secret) < 32 or not secret.strip():
            raise ValueError("token_signing_secret must contain at least 32 characters")
        if self.environment is Environment.PRODUCTION and secret == "development-only-change-this-token-secret":
            raise ValueError("production requires a non-default token_signing_secret")
        if self.default_job_timeout_seconds > self.maximum_job_timeout_seconds:
            raise ValueError("default_job_timeout_seconds must not exceed maximum_job_timeout_seconds")
        if self.ai_max_suggestions_per_response > self.ai_max_candidates_per_request:
            raise ValueError("AI suggestion limit must not exceed candidate limit")
        if (self.s3_access_key_id is None) != (self.s3_secret_access_key is None):
            raise ValueError("S3 access key ID and secret access key must be configured together")
        if self.storage_provider == "s3":
            if not self.s3_bucket or not re.fullmatch(
                r"(?=.{3,63}\Z)[a-z0-9][a-z0-9.-]*[a-z0-9]", self.s3_bucket
            ):
                raise ValueError("S3 storage requires a valid private bucket name")
            if self.s3_endpoint_url:
                endpoint = urlsplit(self.s3_endpoint_url)
                if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
                    raise ValueError("S3 endpoint URL must not contain credentials, query, or fragment")
                if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
                    raise ValueError("S3 endpoint URL must be an absolute HTTP or HTTPS URL")
                if endpoint.scheme == "http" and endpoint.hostname not in {
                    "localhost", "127.0.0.1", "::1", "minio"
                }:
                    raise ValueError("plain HTTP S3 endpoints are restricted to local development")
            if self.environment is Environment.PRODUCTION and self.s3_auto_create_bucket:
                raise ValueError("production S3 buckets must be provisioned explicitly")
        return self

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value().strip()
        if not url.startswith(("postgresql+psycopg://", "sqlite+pysqlite://")):
            raise ValueError("database_url must use postgresql+psycopg or sqlite+pysqlite")
        return SecretStr(url)

    @field_validator(
        "app_name", "app_version", "token_issuer", "token_audience", "worker_id",
        "ai_model_version", "ai_prompt_version",
    )
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

    @field_validator("storage_provider")
    @classmethod
    def validate_storage_provider(cls, value: str) -> str:
        provider = value.strip().lower()
        if provider not in {"local", "s3"}:
            raise ValueError("storage_provider must be 'local' or 's3'")
        return provider

    @field_validator("ai_inference_provider")
    @classmethod
    def validate_ai_inference_provider(cls, value: str) -> str:
        provider = value.strip().lower()
        if provider not in {"disabled", "deterministic"}:
            raise ValueError("ai_inference_provider must be 'disabled' or 'deterministic'")
        return provider
