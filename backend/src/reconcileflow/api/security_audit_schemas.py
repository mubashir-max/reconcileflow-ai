"""Tenant security audit response contracts."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SecurityAuditEventResponse(StrictModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    actor_user_id: uuid.UUID
    event_type: str
    occurred_at: datetime
    details: dict[str, Any]


class SecurityAuditEventListResponse(StrictModel):
    items: list[SecurityAuditEventResponse]
    total: int = Field(ge=0)
    limit: int
    offset: int
