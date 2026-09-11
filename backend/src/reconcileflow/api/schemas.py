"""Stable response contracts for operational API endpoints."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .config import Environment


class StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServiceInfoResponse(StrictResponse):
    name: str
    version: str
    environment: Environment
    api_prefix: str
    documentation_url: str


class HealthResponse(StrictResponse):
    status: str
    service: str
    version: str
    environment: Environment


class WorkerHealthResponse(StrictResponse):
    status: str
    active_workers: int = Field(ge=0)
    stale_workers: int = Field(ge=0)


class ErrorBody(StrictResponse):
    code: str
    message: str
    details: list[dict[str, Any]] = Field(default_factory=list)


class ErrorResponse(StrictResponse):
    error: ErrorBody
