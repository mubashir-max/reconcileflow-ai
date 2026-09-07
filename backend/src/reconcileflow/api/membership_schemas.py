"""Organization membership management request and response contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from reconcileflow.auth import normalize_email

from .auth_schemas import EMAIL_PATTERN, MembershipRole


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddOrganizationMemberRequest(StrictModel):
    email: str = Field(min_length=5, max_length=320)
    role: MembershipRole = MembershipRole.VIEWER

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("email must be a valid address")
        return normalized


class UpdateOrganizationMemberRequest(StrictModel):
    role: MembershipRole


class MemberUserResponse(StrictModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    is_active: bool


class OrganizationMemberResponse(StrictModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user: MemberUserResponse
    role: MembershipRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OrganizationMemberListResponse(StrictModel):
    items: list[OrganizationMemberResponse]
    total: int = Field(ge=0)
