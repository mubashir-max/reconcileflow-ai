"""Safe public contracts for background-job monitoring."""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import Field

from .run_schemas import StrictModel


class BackgroundJobStatusValue(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


class BackgroundJobResponse(StrictModel):
    id: uuid.UUID
    run_id: uuid.UUID
    organization_id: uuid.UUID
    status: BackgroundJobStatusValue
    progress_percentage: int = Field(ge=0, le=100)
    status_message: str | None
    attempt_count: int = Field(ge=0)
    total_attempt_count: int = Field(ge=0)
    manual_retry_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    last_manual_retry_at: datetime | None
    failure_code: str | None
    failure_message: str | None
    scheduled_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancellation_requested_at: datetime | None
    retry_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BackgroundJobListResponse(StrictModel):
    items: list[BackgroundJobResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class BackgroundJobQueueSummary(StrictModel):
    queued: int = Field(ge=0)
    running: int = Field(ge=0)
    retrying: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancel_requested: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    oldest_eligible_age_seconds: int | None = Field(default=None, ge=0)
