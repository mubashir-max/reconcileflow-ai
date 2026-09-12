"""Safe public contracts for advisory AI match suggestions."""

from datetime import datetime
from enum import StrEnum
import uuid

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AISuggestionStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AISuggestionDecision(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AISuggestionDecisionRequest(StrictModel):
    decision: AISuggestionDecision


class AISuggestionResponse(StrictModel):
    id: uuid.UUID
    run_id: uuid.UUID
    status: AISuggestionStatus
    bank_record_ids: list[str]
    erp_invoice_ids: list[str]
    gateway_record_ids: list[str]
    confidence_score: float = Field(ge=0, le=1)
    summary: str
    reason_codes: list[str]
    model_version: str
    prompt_version: str
    reviewed_by_user_id: uuid.UUID | None
    reviewed_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class AISuggestionListResponse(StrictModel):
    items: list[AISuggestionResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class AISuggestionGenerationResponse(StrictModel):
    items: list[AISuggestionResponse]
    generated_count: int = Field(ge=0)
