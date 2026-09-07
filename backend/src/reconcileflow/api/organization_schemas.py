"""Organization discovery and profile request and response contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth_schemas import MembershipRole


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrganizationListItem(StrictModel):
    id: uuid.UUID
    name: str
    slug: str
    role: MembershipRole


class OrganizationListResponse(StrictModel):
    items: list[OrganizationListItem]
    total: int = Field(ge=0)


class OrganizationProfileResponse(StrictModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    current_user_role: MembershipRole
    created_at: datetime
    updated_at: datetime


class UpdateOrganizationRequest(StrictModel):
    name: str = Field(min_length=1, max_length=150)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("organization name must not be blank")
        return normalized
