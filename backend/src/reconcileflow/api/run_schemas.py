"""Public request and response contracts for reconciliation runs."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReconciliationRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ReconciliationConfigurationRequest(StrictModel):
    amount_tolerance: Decimal = Field(default=Decimal("1.00"), ge=0, max_digits=20, decimal_places=4)
    date_tolerance_days: int = Field(default=14, ge=0, le=365)
    maximum_group_size: int = Field(default=5, ge=2, le=10)


class CreateReconciliationRunRequest(StrictModel):
    configuration: ReconciliationConfigurationRequest = Field(default_factory=ReconciliationConfigurationRequest)


class ReconciliationConfigurationResponse(StrictModel):
    amount_tolerance: Decimal
    date_tolerance_days: int
    maximum_group_size: int


class ReconciliationRunResponse(StrictModel):
    id: uuid.UUID
    status: ReconciliationRunStatus
    configuration: ReconciliationConfigurationResponse
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ReconciliationRunListItem(StrictModel):
    id: uuid.UUID
    status: ReconciliationRunStatus
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReconciliationRunListResponse(StrictModel):
    items: list[ReconciliationRunListItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
