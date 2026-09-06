"""Public request and response contracts for password authentication."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from reconcileflow.auth import normalize_email


EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MembershipRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


class RegistrationRequest(StrictModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=150)
    organization_name: str = Field(min_length=1, max_length=150)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("email must be a valid address")
        return normalized

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("password must not be blank")
        return value

    @field_validator("display_name", "organization_name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class LoginRequest(StrictModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_login_email(cls, value: str) -> str:
        return normalize_email(value)


class UserResponse(StrictModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    is_active: bool
    created_at: datetime


class OrganizationResponse(StrictModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool


class MembershipResponse(StrictModel):
    organization: OrganizationResponse
    role: MembershipRole
    is_active: bool


class RegistrationResponse(StrictModel):
    user: UserResponse
    membership: MembershipResponse


class LoginResponse(StrictModel):
    authenticated: bool
    user: UserResponse
    memberships: list[MembershipResponse]
