"""SQLAlchemy models for durable reconciliation data.

Persistence records remain separate from the immutable financial domain models.
Repositories introduced later will translate between the two layers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reconcileflow.persistence.base import Base


RUN_STATUSES = ("PENDING", "RUNNING", "SUCCEEDED", "FAILED")
SOURCE_TYPES = ("BANK_TRANSACTIONS", "ERP_INVOICES", "GATEWAY_SETTLEMENTS")
RESULT_STATUSES = (
    "EXACT_MATCH", "SETTLEMENT_MATCH", "TOLERANCE_MATCH",
    "MANY_TO_ONE_MATCH", "ONE_TO_MANY_MATCH", "DUPLICATE", "REQUIRES_REVIEW",
)
MEMBERSHIP_ROLES = ("OWNER", "ADMIN", "ANALYST", "VIEWER")


class OrganizationRecord(Base):
    """A tenant that owns an isolated ReconcileFlow workspace."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="nonblank_name"),
        CheckConstraint("length(trim(slug)) > 0", name="nonblank_slug"),
        CheckConstraint("slug = lower(slug) AND slug NOT LIKE '% %'", name="normalized_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    memberships: Mapped[list[OrganizationMembershipRecord]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class UserRecord(Base):
    """A login identity; credentials are stored only as password hashes."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(trim(email)) > 3", name="nonblank_email"),
        CheckConstraint("email = lower(trim(email))", name="normalized_email"),
        CheckConstraint("email LIKE '_%@_%'", name="email_has_at_sign"),
        CheckConstraint("length(trim(password_hash)) > 0", name="nonblank_password_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    memberships: Mapped[list[OrganizationMembershipRecord]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class OrganizationMembershipRecord(Base):
    """Assign a user a role inside one organization."""

    __tablename__ = "organization_memberships"
    __table_args__ = (
        CheckConstraint(f"role IN {MEMBERSHIP_ROLES}", name="valid_role"),
        UniqueConstraint("organization_id", "user_id", name="uq_organization_memberships_organization_user"),
        Index("ix_organization_memberships_user_active", "user_id", "is_active"),
        Index("ix_organization_memberships_organization_role", "organization_id", "role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    organization: Mapped[OrganizationRecord] = relationship(back_populates="memberships")
    user: Mapped[UserRecord] = relationship(back_populates="memberships")


class ReconciliationRunRecord(Base):
    """One requested execution of the reconciliation workflow."""

    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="valid_status"),
        CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="valid_time_range"),
        Index("ix_reconciliation_runs_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    source_files: Mapped[list[SourceFileRecord]] = relationship(back_populates="run")
    configuration: Mapped[ConfigurationSnapshotRecord | None] = relationship(back_populates="run", uselist=False)
    results: Mapped[list[ReconciliationResultRecord]] = relationship(back_populates="run")
    audit_events: Mapped[list[AuditEventRecord]] = relationship(back_populates="run", order_by="AuditEventRecord.sequence_number")


class SourceFileRecord(Base):
    """Metadata for one source file supplied to a reconciliation run."""

    __tablename__ = "source_files"
    __table_args__ = (
        CheckConstraint(f"source_type IN {SOURCE_TYPES}", name="valid_source_type"),
        CheckConstraint("size_bytes >= 0", name="nonnegative_size"),
        CheckConstraint("row_count IS NULL OR row_count >= 0", name="nonnegative_row_count"),
        UniqueConstraint("run_id", "source_type", name="uq_source_files_run_source_type"),
        Index("ix_source_files_checksum_sha256", "checksum_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100))
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer)
    storage_key: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run: Mapped[ReconciliationRunRecord] = relationship(back_populates="source_files")


class ConfigurationSnapshotRecord(Base):
    """Immutable matching configuration captured for reproducibility."""

    __tablename__ = "configuration_snapshots"
    __table_args__ = (
        CheckConstraint("amount_tolerance >= 0", name="nonnegative_amount_tolerance"),
        CheckConstraint("date_tolerance_days >= 0", name="nonnegative_date_tolerance"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), nullable=False, unique=True)
    amount_tolerance: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False, default=Decimal("0"))
    date_tolerance_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run: Mapped[ReconciliationRunRecord] = relationship(back_populates="configuration")


class ReconciliationResultRecord(Base):
    """Explainable result produced by one deterministic rule."""

    __tablename__ = "reconciliation_results"
    __table_args__ = (
        CheckConstraint(f"status IN {RESULT_STATUSES}", name="valid_status"),
        CheckConstraint("amount_difference IS NULL OR amount_difference >= 0", name="nonnegative_difference"),
        CheckConstraint("currency IS NULL OR length(currency) = 3", name="valid_currency_length"),
        UniqueConstraint("run_id", "external_result_id", name="uq_reconciliation_results_run_external_id"),
        Index("ix_reconciliation_results_run_status", "run_id", "status"),
        Index("ix_reconciliation_results_run_review", "run_id", "requires_review"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), nullable=False)
    external_result_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    rule: Mapped[str] = mapped_column(String(100), nullable=False)
    bank_source_record_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    erp_invoice_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    gateway_source_record_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    expected_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    actual_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    amount_difference: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    currency: Mapped[str | None] = mapped_column(String(3))
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run: Mapped[ReconciliationRunRecord] = relationship(back_populates="results")


class AuditEventRecord(Base):
    """Append-only structured event belonging to a reconciliation run."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("sequence_number >= 1", name="positive_sequence"),
        UniqueConstraint("run_id", "sequence_number", name="uq_audit_events_run_sequence"),
        Index("ix_audit_events_run_occurred_at", "run_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    run: Mapped[ReconciliationRunRecord] = relationship(back_populates="audit_events")
