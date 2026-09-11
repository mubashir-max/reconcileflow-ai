"""API contracts for execution, results, and audit history."""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from typing import Literal

from pydantic import Field, field_validator

from .run_schemas import ReconciliationRunStatus, StrictModel
from .job_schemas import BackgroundJobPriorityValue


class ReconciliationResultStatus(StrEnum):
    EXACT_MATCH = "EXACT_MATCH"
    SETTLEMENT_MATCH = "SETTLEMENT_MATCH"
    TOLERANCE_MATCH = "TOLERANCE_MATCH"
    MANY_TO_ONE_MATCH = "MANY_TO_ONE_MATCH"
    ONE_TO_MANY_MATCH = "ONE_TO_MANY_MATCH"
    DUPLICATE = "DUPLICATE"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


class ExecutionResponse(StrictModel):
    run_id: uuid.UUID
    status: ReconciliationRunStatus
    result_count: int = Field(ge=0)
    results_requiring_review: int = Field(ge=0)


class ExecutionAcceptedResponse(StrictModel):
    job_id: uuid.UUID
    run_id: uuid.UUID
    status: Literal["QUEUED"]
    scheduled_at: datetime
    timeout_seconds: int = Field(ge=30)
    priority: BackgroundJobPriorityValue


class ExecutionRequest(StrictModel):
    scheduled_at: datetime | None = None
    timeout_seconds: int | None = Field(default=None, ge=30)
    priority: BackgroundJobPriorityValue = BackgroundJobPriorityValue.NORMAL

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("scheduled_at must include a timezone offset")
        return value


class ResultResponse(StrictModel):
    id: uuid.UUID
    run_id: uuid.UUID
    external_result_id: str
    status: ReconciliationResultStatus
    rule: str
    bank_source_record_ids: list[str]
    erp_invoice_ids: list[str]
    gateway_source_record_ids: list[str]
    expected_amount: Decimal | None
    actual_amount: Decimal | None
    amount_difference: Decimal | None
    currency: str | None
    explanation: str
    requires_review: bool
    created_at: datetime


class ResultListResponse(StrictModel):
    items: list[ResultResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class AuditEventResponse(StrictModel):
    id: uuid.UUID
    run_id: uuid.UUID
    sequence_number: int = Field(ge=1)
    event_type: str
    occurred_at: datetime
    details: dict[str, Any]


class AuditEventListResponse(StrictModel):
    items: list[AuditEventResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
