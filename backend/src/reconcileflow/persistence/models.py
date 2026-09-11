"""SQLAlchemy models for durable reconciliation data.

Persistence records remain separate from the immutable financial domain models.
Repositories introduced later will translate between the two layers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
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


class BackgroundJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


class BackgroundJobPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


BACKGROUND_JOB_STATUSES = tuple(status.value for status in BackgroundJobStatus)
BACKGROUND_JOB_PRIORITIES = tuple(priority.value for priority in BackgroundJobPriority)
WORKER_STATUSES = ("RUNNING", "STOPPED")


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
    reconciliation_runs: Mapped[list[ReconciliationRunRecord]] = relationship(back_populates="organization")
    background_jobs: Mapped[list[BackgroundJobRecord]] = relationship(back_populates="organization")


class UserRecord(Base):
    """A login identity; credentials are stored only as password hashes."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(trim(email)) > 3", name="nonblank_email"),
        CheckConstraint("email = lower(trim(email))", name="normalized_email"),
        CheckConstraint("email LIKE '_%@_%'", name="email_has_at_sign"),
        CheckConstraint("length(trim(password_hash)) > 0", name="nonblank_password_hash"),
        CheckConstraint("failed_login_attempts >= 0", name="nonnegative_failed_login_attempts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    memberships: Mapped[list[OrganizationMembershipRecord]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list[RefreshTokenRecord]] = relationship(
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


class RefreshTokenRecord(Base):
    """Hashed, revocable server-side state for one issued refresh token."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint("length(token_hash) = 64", name="valid_token_hash"),
        CheckConstraint("expires_at > created_at", name="valid_expiration"),
        Index("ix_refresh_tokens_user_expires_at", "user_id", "expires_at"),
        Index("ix_refresh_tokens_family_revoked_at", "family_id", "revoked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[UserRecord] = relationship(back_populates="refresh_tokens")


class ReconciliationRunRecord(Base):
    """One requested execution of the reconciliation workflow."""

    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="valid_status"),
        CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="valid_time_range"),
        Index("ix_reconciliation_runs_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
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
    organization: Mapped[OrganizationRecord] = relationship(back_populates="reconciliation_runs")
    background_job: Mapped[BackgroundJobRecord | None] = relationship(
        back_populates="run", uselist=False
    )


class BackgroundJobRecord(Base):
    """Durable queue state for asynchronous reconciliation execution."""

    __tablename__ = "background_jobs"
    __table_args__ = (
        CheckConstraint(f"status IN {BACKGROUND_JOB_STATUSES}", name="valid_status"),
        CheckConstraint(f"priority IN {BACKGROUND_JOB_PRIORITIES}", name="valid_priority"),
        CheckConstraint(
            "progress_percentage >= 0 AND progress_percentage <= 100",
            name="valid_progress_percentage",
        ),
        CheckConstraint("attempt_count >= 0", name="nonnegative_attempt_count"),
        CheckConstraint("total_attempt_count >= 0", name="nonnegative_total_attempt_count"),
        CheckConstraint("manual_retry_count >= 0", name="nonnegative_manual_retry_count"),
        CheckConstraint("max_attempts >= 1", name="positive_max_attempts"),
        CheckConstraint("timeout_seconds >= 30", name="valid_timeout_seconds"),
        CheckConstraint("attempt_count <= max_attempts", name="attempts_within_limit"),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="valid_execution_time_range",
        ),
        Index("ix_background_jobs_queue", "status", "priority", "scheduled_at", "retry_at", "created_at"),
        Index("ix_background_jobs_organization_status", "organization_id", "status"),
        Index("ix_background_jobs_running_heartbeat", "status", "heartbeat_at"),
        Index("ix_background_jobs_terminal_completed", "status", "completed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="QUEUED", server_default="QUEUED")
    priority: Mapped[str] = mapped_column(String(12), nullable=False, default="NORMAL", server_default="NORMAL")
    progress_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status_message: Mapped[str | None] = mapped_column(String(500))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    manual_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900, server_default="900")
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_manual_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(200))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    organization: Mapped[OrganizationRecord] = relationship(back_populates="background_jobs")
    run: Mapped[ReconciliationRunRecord] = relationship(back_populates="background_job")


class WorkerRecord(Base):
    """Internal worker lifecycle state; never returned with its identifier publicly."""

    __tablename__ = "workers"
    __table_args__ = (
        CheckConstraint(f"status IN {WORKER_STATUSES}", name="valid_status"),
        Index("ix_workers_status_heartbeat", "status", "heartbeat_at"),
        Index("ix_workers_status_stopped", "status", "stopped_at"),
    )

    worker_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class SecurityAuditEventRecord(Base):
    """Append-only, tenant-scoped security event without credential material."""

    __tablename__ = "security_audit_events"
    __table_args__ = (
        Index("ix_security_audit_events_organization_occurred_at", "organization_id", "occurred_at"),
        Index("ix_security_audit_events_actor_occurred_at", "actor_user_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
