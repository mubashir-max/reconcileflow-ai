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


class OrganizationStorageUsageResponse(StrictModel):
    organization_id: uuid.UUID
    used_bytes: int = Field(ge=0)
    quota_bytes: int | None = Field(default=None, ge=0)
    remaining_bytes: int | None = Field(default=None, ge=0)
    utilization_percent: float | None = Field(default=None, ge=0, le=100)


class UpdateOrganizationStorageQuotaRequest(StrictModel):
    quota_bytes: int | None = Field(default=None, ge=0)


class OrganizationAIUsagePolicy(StrictModel):
    organization_id: uuid.UUID
    hosted_ai_enabled: bool
    daily_request_limit: int = Field(ge=0)
    monthly_request_limit: int = Field(ge=0)
    daily_token_limit: int = Field(ge=0)
    monthly_token_limit: int = Field(ge=0)


class UpdateOrganizationAIUsagePolicyRequest(StrictModel):
    hosted_ai_enabled: bool
    daily_request_limit: int = Field(ge=0, le=1_000_000)
    monthly_request_limit: int = Field(ge=0, le=10_000_000)
    daily_token_limit: int = Field(ge=0, le=10_000_000_000)
    monthly_token_limit: int = Field(ge=0, le=100_000_000_000)


class OrganizationAIUsageResponse(OrganizationAIUsagePolicy):
    daily_requests: int = Field(ge=0)
    daily_tokens: int = Field(ge=0)
    monthly_requests: int = Field(ge=0)
    monthly_tokens: int = Field(ge=0)
