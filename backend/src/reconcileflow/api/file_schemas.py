"""Public response contracts for uploaded source-file metadata."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceFileType(StrEnum):
    BANK_TRANSACTIONS = "BANK_TRANSACTIONS"
    ERP_INVOICES = "ERP_INVOICES"
    GATEWAY_SETTLEMENTS = "GATEWAY_SETTLEMENTS"


class SourceFileMetadataResponse(StrictModel):
    id: uuid.UUID
    run_id: uuid.UUID
    source_type: SourceFileType
    original_filename: str
    content_type: str
    size_bytes: int = Field(ge=0)
    checksum_sha256: str = Field(min_length=64, max_length=64)
    row_count: int | None = Field(default=None, ge=0)
    created_at: datetime


class SourceFileListResponse(StrictModel):
    items: list[SourceFileMetadataResponse]
    total: int = Field(ge=0)


class PresignedUploadRequest(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=200)
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(default=1, ge=1)


class PresignedUploadResponse(StrictModel):
    storage_key: str
    url: str
    fields: dict[str, str]
    expires_in_seconds: int


class PresignedDownloadResponse(StrictModel):
    url: str
    expires_in_seconds: int


class DirectUploadFinalizationRequest(StrictModel):
    storage_key: str = Field(min_length=36, max_length=100)
    source_type: SourceFileType
    original_filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(ge=1)
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
