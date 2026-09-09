"""Focused SQLAlchemy repositories for ReconcileFlow persistence records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from reconcileflow.audit import AuditEvent
from reconcileflow.reconciliation import ReconciliationConfig, ReconciliationResult

from .errors import InvalidStatusTransitionError, PersistenceConflictError, RecordNotFoundError
from .models import (
    AuditEventRecord,
    BackgroundJobRecord,
    BackgroundJobStatus,
    ConfigurationSnapshotRecord,
    OrganizationMembershipRecord,
    OrganizationRecord,
    ReconciliationResultRecord,
    ReconciliationRunRecord,
    RefreshTokenRecord,
    SecurityAuditEventRecord,
    RESULT_STATUSES,
    SourceFileRecord,
    UserRecord,
)


@dataclass(frozen=True, slots=True)
class Page:
    """Validated offset pagination shared by repository list operations."""

    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if isinstance(self.offset, bool) or self.offset < 0:
            raise ValueError("offset must be a non-negative integer")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include timezone information")
    return value.astimezone(UTC)


class OrganizationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, name: str, slug: str) -> OrganizationRecord:
        record = OrganizationRecord(name=name.strip(), slug=slug)
        self._session.add(record)
        self._session.flush()
        return record

    def slug_exists(self, slug: str) -> bool:
        return self._session.scalar(select(OrganizationRecord.id).where(OrganizationRecord.slug == slug)) is not None

    def get(self, organization_id: uuid.UUID) -> OrganizationRecord:
        record = self._session.get(OrganizationRecord, organization_id)
        if record is None:
            raise RecordNotFoundError(f"organization {organization_id} was not found")
        return record

    def update_name(self, record: OrganizationRecord, name: str) -> OrganizationRecord:
        record.name = name.strip()
        self._session.flush()
        return record


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, email: str, password_hash: str, display_name: str | None = None) -> UserRecord:
        record = UserRecord(
            email=email,
            password_hash=password_hash,
            display_name=display_name.strip() if display_name else None,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def get_by_email(self, email: str, *, lock: bool = False) -> UserRecord | None:
        statement = select(UserRecord).where(UserRecord.email == email)
        if lock:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    def get(self, user_id: uuid.UUID, *, lock: bool = False) -> UserRecord | None:
        statement = select(UserRecord).where(UserRecord.id == user_id)
        if lock:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    def email_exists(self, email: str) -> bool:
        return self._session.scalar(select(UserRecord.id).where(UserRecord.email == email)) is not None

    def update_password(self, record: UserRecord, password_hash: str) -> UserRecord:
        record.password_hash = password_hash
        self._session.flush()
        return record

    def record_failed_login(
        self, record: UserRecord, *, threshold: int, locked_until: datetime
    ) -> bool:
        record.failed_login_attempts += 1
        newly_locked = record.failed_login_attempts >= threshold
        if newly_locked:
            record.locked_until = _utc(locked_until)
        self._session.flush()
        return newly_locked

    def reset_login_protection(self, record: UserRecord) -> None:
        if record.failed_login_attempts or record.locked_until is not None:
            record.failed_login_attempts = 0
            record.locked_until = None
            self._session.flush()


class OrganizationMembershipRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, role: str
    ) -> OrganizationMembershipRecord:
        record = OrganizationMembershipRecord(
            organization_id=organization_id, user_id=user_id, role=role
        )
        self._session.add(record)
        self._session.flush()
        return record

    def list_for_user(self, user_id: uuid.UUID) -> list[OrganizationMembershipRecord]:
        statement = (
            select(OrganizationMembershipRecord)
            .where(OrganizationMembershipRecord.user_id == user_id)
            .order_by(OrganizationMembershipRecord.created_at, OrganizationMembershipRecord.id)
        )
        return list(self._session.scalars(statement))

    def get_active(self, *, organization_id: uuid.UUID, user_id: uuid.UUID) -> OrganizationMembershipRecord | None:
        return self._session.scalar(
            select(OrganizationMembershipRecord)
            .join(OrganizationRecord)
            .where(
                OrganizationMembershipRecord.organization_id == organization_id,
                OrganizationMembershipRecord.user_id == user_id,
                OrganizationMembershipRecord.is_active.is_(True),
                OrganizationRecord.is_active.is_(True),
            )
        )

    def get(self, membership_id: uuid.UUID, *, organization_id: uuid.UUID, lock: bool = False) -> OrganizationMembershipRecord:
        statement = select(OrganizationMembershipRecord).where(
            OrganizationMembershipRecord.id == membership_id,
            OrganizationMembershipRecord.organization_id == organization_id,
        )
        if lock:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        if record is None:
            raise RecordNotFoundError(f"organization membership {membership_id} was not found")
        return record

    def get_for_user(self, *, organization_id: uuid.UUID, user_id: uuid.UUID) -> OrganizationMembershipRecord | None:
        return self._session.scalar(
            select(OrganizationMembershipRecord).where(
                OrganizationMembershipRecord.organization_id == organization_id,
                OrganizationMembershipRecord.user_id == user_id,
            )
        )

    def list_for_organization(self, organization_id: uuid.UUID) -> list[OrganizationMembershipRecord]:
        statement = (
            select(OrganizationMembershipRecord)
            .where(OrganizationMembershipRecord.organization_id == organization_id)
            .order_by(OrganizationMembershipRecord.created_at, OrganizationMembershipRecord.id)
        )
        return list(self._session.scalars(statement))

    def count_active_owners(self, organization_id: uuid.UUID) -> int:
        return self._session.scalar(
            select(func.count()).select_from(OrganizationMembershipRecord).where(
                OrganizationMembershipRecord.organization_id == organization_id,
                OrganizationMembershipRecord.role == "OWNER",
                OrganizationMembershipRecord.is_active.is_(True),
            )
        ) or 0

    def set_role(self, record: OrganizationMembershipRecord, role: str) -> OrganizationMembershipRecord:
        record.role = role
        self._session.flush()
        return record

    def deactivate(self, record: OrganizationMembershipRecord) -> OrganizationMembershipRecord:
        record.is_active = False
        self._session.flush()
        return record


class RefreshTokenRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        token_id: uuid.UUID,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshTokenRecord:
        record = RefreshTokenRecord(
            id=token_id,
            user_id=user_id,
            family_id=family_id,
            token_hash=token_hash,
            expires_at=_utc(expires_at),
        )
        self._session.add(record)
        self._session.flush()
        return record

    def get_by_hash(self, token_hash: str, *, lock: bool = False) -> RefreshTokenRecord | None:
        statement = select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == token_hash)
        if lock:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    def rotate(
        self,
        current: RefreshTokenRecord,
        *,
        replacement_id: uuid.UUID,
        replacement_hash: str,
        replacement_expires_at: datetime,
        at: datetime,
    ) -> RefreshTokenRecord:
        replacement = self.create(
            token_id=replacement_id,
            user_id=current.user_id,
            family_id=current.family_id,
            token_hash=replacement_hash,
            expires_at=replacement_expires_at,
        )
        current.revoked_at = _utc(at)
        current.replaced_by_id = replacement.id
        self._session.flush()
        return replacement

    def revoke(self, record: RefreshTokenRecord, *, at: datetime) -> None:
        if record.revoked_at is None:
            record.revoked_at = _utc(at)
            self._session.flush()

    def revoke_family(self, family_id: uuid.UUID, *, at: datetime) -> int:
        records = list(self._session.scalars(
            select(RefreshTokenRecord).where(
                RefreshTokenRecord.family_id == family_id,
                RefreshTokenRecord.revoked_at.is_(None),
            ).with_for_update()
        ))
        revoked_at = _utc(at)
        for record in records:
            record.revoked_at = revoked_at
        self._session.flush()
        return len(records)

    def revoke_all_for_user(self, user_id: uuid.UUID, *, at: datetime) -> int:
        records = list(self._session.scalars(
            select(RefreshTokenRecord).where(
                RefreshTokenRecord.user_id == user_id,
                RefreshTokenRecord.revoked_at.is_(None),
            ).with_for_update()
        ))
        revoked_at = _utc(at)
        for record in records:
            record.revoked_at = revoked_at
        self._session.flush()
        return len(records)


class ReconciliationRunRepository:
    _TRANSITIONS = {
        "PENDING": frozenset(("RUNNING", "FAILED")),
        "RUNNING": frozenset(("SUCCEEDED", "FAILED")),
        "SUCCEEDED": frozenset(),
        "FAILED": frozenset(),
    }

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, organization_id: uuid.UUID, run_id: uuid.UUID | None = None) -> ReconciliationRunRecord:
        record = ReconciliationRunRecord(id=run_id or uuid.uuid4(), organization_id=organization_id, status="PENDING")
        self._session.add(record)
        self._session.flush()
        return record

    def get(self, run_id: uuid.UUID, *, organization_id: uuid.UUID | None = None, lock: bool = False) -> ReconciliationRunRecord:
        statement = select(ReconciliationRunRecord).where(ReconciliationRunRecord.id == run_id)
        if organization_id is not None:
            statement = statement.where(ReconciliationRunRecord.organization_id == organization_id)
        if lock:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        if record is None:
            raise RecordNotFoundError(f"reconciliation run {run_id} was not found")
        return record

    def list(self, *, organization_id: uuid.UUID | None = None, page: Page = Page(), status: str | None = None) -> list[ReconciliationRunRecord]:
        statement = select(ReconciliationRunRecord)
        if organization_id is not None:
            statement = statement.where(ReconciliationRunRecord.organization_id == organization_id)
        if status is not None:
            if status not in self._TRANSITIONS:
                raise ValueError("invalid reconciliation run status")
            statement = statement.where(ReconciliationRunRecord.status == status)
        statement = statement.order_by(ReconciliationRunRecord.created_at.desc(), ReconciliationRunRecord.id).limit(page.limit).offset(page.offset)
        return list(self._session.scalars(statement))

    def count(self, *, organization_id: uuid.UUID | None = None, status: str | None = None) -> int:
        statement = select(func.count()).select_from(ReconciliationRunRecord)
        if organization_id is not None:
            statement = statement.where(ReconciliationRunRecord.organization_id == organization_id)
        if status is not None:
            if status not in self._TRANSITIONS:
                raise ValueError("invalid reconciliation run status")
            statement = statement.where(ReconciliationRunRecord.status == status)
        return self._session.scalar(statement) or 0

    def transition(
        self,
        run_id: uuid.UUID,
        status: str,
        *,
        at: datetime | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        organization_id: uuid.UUID | None = None,
    ) -> ReconciliationRunRecord:
        record = self.get(run_id, organization_id=organization_id, lock=True)
        if status not in self._TRANSITIONS[record.status]:
            raise InvalidStatusTransitionError(f"cannot transition run from {record.status} to {status}")
        occurred_at = _utc(at or datetime.now(UTC))
        record.status = status
        if status == "RUNNING":
            record.started_at = occurred_at
        else:
            record.finished_at = occurred_at
            record.error_code = error_code if status == "FAILED" else None
            record.error_message = error_message if status == "FAILED" else None
        self._session.flush()
        return record


class BackgroundJobRepository:
    """Tenant-scoped queue operations for reconciliation workers."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        organization_id: uuid.UUID,
        run_id: uuid.UUID,
        scheduled_at: datetime | None = None,
        max_attempts: int = 3,
    ) -> BackgroundJobRecord:
        if isinstance(max_attempts, bool) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        run_exists = self._session.scalar(
            select(ReconciliationRunRecord.id).where(
                ReconciliationRunRecord.id == run_id,
                ReconciliationRunRecord.organization_id == organization_id,
            )
        )
        if run_exists is None:
            raise RecordNotFoundError(f"reconciliation run {run_id} was not found")
        if self._session.scalar(
            select(BackgroundJobRecord.id).where(BackgroundJobRecord.run_id == run_id)
        ) is not None:
            raise PersistenceConflictError(f"run {run_id} already has a background job")
        record = BackgroundJobRecord(
            organization_id=organization_id,
            run_id=run_id,
            scheduled_at=_utc(scheduled_at or datetime.now(UTC)),
            max_attempts=max_attempts,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def get(
        self,
        job_id: uuid.UUID,
        *,
        organization_id: uuid.UUID,
        lock: bool = False,
    ) -> BackgroundJobRecord:
        statement = select(BackgroundJobRecord).where(
            BackgroundJobRecord.id == job_id,
            BackgroundJobRecord.organization_id == organization_id,
        )
        if lock:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        if record is None:
            raise RecordNotFoundError(f"background job {job_id} was not found")
        return record

    def get_for_run(
        self,
        run_id: uuid.UUID,
        *,
        organization_id: uuid.UUID,
    ) -> BackgroundJobRecord | None:
        return self._session.scalar(
            select(BackgroundJobRecord).where(
                BackgroundJobRecord.run_id == run_id,
                BackgroundJobRecord.organization_id == organization_id,
            )
        )

    def list(
        self,
        *,
        organization_id: uuid.UUID,
        status: BackgroundJobStatus | str | None = None,
        page: Page = Page(),
    ) -> list[BackgroundJobRecord]:
        statement = select(BackgroundJobRecord).where(
            BackgroundJobRecord.organization_id == organization_id
        )
        if status is not None:
            normalized_status = self._status_value(status)
            statement = statement.where(BackgroundJobRecord.status == normalized_status)
        statement = statement.order_by(
            BackgroundJobRecord.created_at.desc(), BackgroundJobRecord.id
        ).limit(page.limit).offset(page.offset)
        return list(self._session.scalars(statement))

    def count(
        self,
        *,
        organization_id: uuid.UUID,
        status: BackgroundJobStatus | str | None = None,
    ) -> int:
        statement = select(func.count()).select_from(BackgroundJobRecord).where(
            BackgroundJobRecord.organization_id == organization_id
        )
        if status is not None:
            statement = statement.where(
                BackgroundJobRecord.status == self._status_value(status)
            )
        return int(self._session.scalar(statement) or 0)

    def claim_next(
        self,
        *,
        worker_id: str,
        at: datetime | None = None,
        organization_id: uuid.UUID | None = None,
    ) -> BackgroundJobRecord | None:
        worker_id = worker_id.strip()
        if not worker_id or len(worker_id) > 200:
            raise ValueError("worker_id must contain between 1 and 200 characters")
        claimed_at = _utc(at or datetime.now(UTC))
        statement = select(BackgroundJobRecord).where(
            BackgroundJobRecord.status == BackgroundJobStatus.QUEUED.value,
            BackgroundJobRecord.scheduled_at <= claimed_at,
            or_(BackgroundJobRecord.retry_at.is_(None), BackgroundJobRecord.retry_at <= claimed_at),
            BackgroundJobRecord.attempt_count < BackgroundJobRecord.max_attempts,
        )
        if organization_id is not None:
            statement = statement.where(BackgroundJobRecord.organization_id == organization_id)
        statement = statement.order_by(
            BackgroundJobRecord.scheduled_at,
            BackgroundJobRecord.retry_at,
            BackgroundJobRecord.created_at,
            BackgroundJobRecord.id,
        ).limit(1)
        if self._session.bind is not None and self._session.bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        else:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        if record is None:
            return None
        record.status = BackgroundJobStatus.RUNNING.value
        record.attempt_count += 1
        record.total_attempt_count += 1
        record.started_at = claimed_at
        record.claimed_by = worker_id
        record.heartbeat_at = claimed_at
        record.completed_at = None
        record.retry_at = None
        record.failure_code = None
        record.failure_message = None
        self._session.flush()
        return record

    def retry_failed(
        self,
        job_id: uuid.UUID,
        *,
        organization_id: uuid.UUID,
        max_manual_retries: int,
        at: datetime | None = None,
    ) -> BackgroundJobRecord:
        if isinstance(max_manual_retries, bool) or max_manual_retries < 1:
            raise ValueError("max_manual_retries must be a positive integer")
        record = self.get(job_id, organization_id=organization_id, lock=True)
        if record.status != BackgroundJobStatus.FAILED.value:
            raise InvalidStatusTransitionError("only failed background jobs can be retried")
        if record.manual_retry_count >= max_manual_retries:
            raise InvalidStatusTransitionError("manual retry limit has been reached")
        if self._session.scalar(
            select(func.count()).select_from(ReconciliationResultRecord).where(
                ReconciliationResultRecord.run_id == record.run_id
            )
        ):
            raise InvalidStatusTransitionError("jobs with persisted results cannot be retried")
        run = self._session.scalar(
            select(ReconciliationRunRecord).where(
                ReconciliationRunRecord.id == record.run_id,
                ReconciliationRunRecord.organization_id == organization_id,
            ).with_for_update()
        )
        if run is None or run.status != "FAILED":
            raise InvalidStatusTransitionError("the associated run is not retryable")

        retried_at = _utc(at or datetime.now(UTC))
        record.status = BackgroundJobStatus.QUEUED.value
        record.progress_percentage = 0
        record.status_message = "Manual retry queued"
        record.attempt_count = 0
        record.manual_retry_count += 1
        record.last_manual_retry_at = retried_at
        record.scheduled_at = retried_at
        record.started_at = None
        record.completed_at = None
        record.cancellation_requested_at = None
        record.retry_at = None
        record.claimed_by = None
        record.heartbeat_at = None
        record.failure_code = None
        record.failure_message = None
        run.status = "PENDING"
        run.started_at = None
        run.finished_at = None
        run.error_code = None
        run.error_message = None
        self._session.flush()
        return record

    def heartbeat(
        self,
        job_id: uuid.UUID,
        *,
        organization_id: uuid.UUID,
        worker_id: str,
        at: datetime | None = None,
    ) -> BackgroundJobRecord:
        record = self.get(job_id, organization_id=organization_id, lock=True)
        if record.status not in {
            BackgroundJobStatus.RUNNING.value,
            BackgroundJobStatus.CANCEL_REQUESTED.value,
        } or record.claimed_by != worker_id:
            raise InvalidStatusTransitionError("background job lease is not owned by this worker")
        record.heartbeat_at = _utc(at or datetime.now(UTC))
        self._session.flush()
        return record

    def recover_stale(
        self,
        *,
        stale_before: datetime,
        at: datetime | None = None,
    ) -> int:
        recovered_at = _utc(at or datetime.now(UTC))
        cutoff = _utc(stale_before)
        statement = select(BackgroundJobRecord).where(
            BackgroundJobRecord.status.in_((
                BackgroundJobStatus.RUNNING.value,
                BackgroundJobStatus.CANCEL_REQUESTED.value,
            )),
            BackgroundJobRecord.heartbeat_at <= cutoff,
        ).with_for_update()
        records = list(self._session.scalars(statement))
        for record in records:
            if record.status == BackgroundJobStatus.CANCEL_REQUESTED.value:
                record.status = BackgroundJobStatus.CANCELLED.value
                record.completed_at = recovered_at
                record.status_message = "Cancelled after worker interruption"
            elif record.attempt_count < record.max_attempts:
                record.status = BackgroundJobStatus.QUEUED.value
                record.retry_at = recovered_at
                record.started_at = None
                record.status_message = "Recovered after worker interruption"
            else:
                record.status = BackgroundJobStatus.FAILED.value
                record.completed_at = recovered_at
                record.failure_code = "WORKER_INTERRUPTED"
                record.failure_message = "Background processing was interrupted."
            record.claimed_by = None
            record.heartbeat_at = None
        self._session.flush()
        return len(records)

    def update_progress(
        self,
        job_id: uuid.UUID,
        *,
        organization_id: uuid.UUID,
        progress_percentage: int,
        status_message: str | None = None,
    ) -> BackgroundJobRecord:
        if isinstance(progress_percentage, bool) or not 0 <= progress_percentage <= 100:
            raise ValueError("progress_percentage must be between 0 and 100")
        record = self.get(job_id, organization_id=organization_id, lock=True)
        if record.status not in {
            BackgroundJobStatus.RUNNING.value,
            BackgroundJobStatus.CANCEL_REQUESTED.value,
        }:
            raise InvalidStatusTransitionError(
                f"cannot update progress for a {record.status} background job"
            )
        record.progress_percentage = progress_percentage
        record.status_message = status_message.strip()[:500] if status_message else None
        self._session.flush()
        return record

    def request_cancellation(
        self, job_id: uuid.UUID, *, organization_id: uuid.UUID, at: datetime | None = None
    ) -> BackgroundJobRecord:
        record = self.get(job_id, organization_id=organization_id, lock=True)
        if record.status not in {
            BackgroundJobStatus.QUEUED.value,
            BackgroundJobStatus.RUNNING.value,
        }:
            raise InvalidStatusTransitionError(
                f"cannot cancel a {record.status} background job"
            )
        requested_at = _utc(at or datetime.now(UTC))
        record.cancellation_requested_at = requested_at
        if record.status == BackgroundJobStatus.QUEUED.value:
            record.status = BackgroundJobStatus.CANCELLED.value
            record.completed_at = requested_at
            record.status_message = "Cancelled before processing"
        else:
            record.status = BackgroundJobStatus.CANCEL_REQUESTED.value
            record.status_message = "Cancellation requested"
        self._session.flush()
        return record

    def complete(
        self,
        job_id: uuid.UUID,
        status: BackgroundJobStatus | str,
        *,
        organization_id: uuid.UUID,
        at: datetime | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
        retry_at: datetime | None = None,
    ) -> BackgroundJobRecord:
        record = self.get(job_id, organization_id=organization_id, lock=True)
        target = self._status_value(status)
        allowed = {
            BackgroundJobStatus.RUNNING.value: {
                BackgroundJobStatus.SUCCEEDED.value,
                BackgroundJobStatus.FAILED.value,
            },
            BackgroundJobStatus.CANCEL_REQUESTED.value: {
                BackgroundJobStatus.CANCELLED.value,
                BackgroundJobStatus.FAILED.value,
            },
        }
        if target not in allowed.get(record.status, set()):
            raise InvalidStatusTransitionError(
                f"cannot transition background job from {record.status} to {target}"
            )
        completed_at = _utc(at or datetime.now(UTC))
        if target == BackgroundJobStatus.FAILED.value and retry_at is not None:
            if record.attempt_count >= record.max_attempts:
                raise InvalidStatusTransitionError("background job has exhausted its attempts")
            record.status = BackgroundJobStatus.QUEUED.value
            record.retry_at = _utc(retry_at)
            record.status_message = "Retry scheduled"
        else:
            record.status = target
            record.completed_at = completed_at
            record.progress_percentage = 100 if target == BackgroundJobStatus.SUCCEEDED.value else record.progress_percentage
        record.claimed_by = None
        record.heartbeat_at = None
        if target == BackgroundJobStatus.FAILED.value:
            record.failure_code = failure_code.strip()[:100] if failure_code else None
            record.failure_message = failure_message.strip()[:2000] if failure_message else None
        self._session.flush()
        return record

    @staticmethod
    def _status_value(status: BackgroundJobStatus | str) -> str:
        try:
            return BackgroundJobStatus(status).value
        except ValueError as error:
            raise ValueError("invalid background job status") from error

class SourceFileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        *,
        run_id: uuid.UUID,
        source_type: str,
        original_filename: str,
        checksum_sha256: str,
        size_bytes: int,
        content_type: str | None = None,
        row_count: int | None = None,
        storage_key: str | None = None,
    ) -> SourceFileRecord:
        existing = self._session.scalar(select(SourceFileRecord.id).where(SourceFileRecord.run_id == run_id, SourceFileRecord.source_type == source_type))
        if existing is not None:
            raise PersistenceConflictError(f"run {run_id} already has a {source_type} source file")
        record = SourceFileRecord(run_id=run_id, source_type=source_type, original_filename=original_filename, checksum_sha256=checksum_sha256, size_bytes=size_bytes, content_type=content_type, row_count=row_count, storage_key=storage_key)
        self._session.add(record)
        self._session.flush()
        return record

    def get(self, file_id: uuid.UUID, *, organization_id: uuid.UUID | None = None) -> SourceFileRecord:
        statement = select(SourceFileRecord).where(SourceFileRecord.id == file_id)
        if organization_id is not None:
            statement = statement.join(ReconciliationRunRecord).where(
                ReconciliationRunRecord.organization_id == organization_id
            )
        record = self._session.scalar(statement)
        if record is None:
            raise RecordNotFoundError(f"source file {file_id} was not found")
        return record

    def list_for_run(self, run_id: uuid.UUID) -> list[SourceFileRecord]:
        statement = select(SourceFileRecord).where(SourceFileRecord.run_id == run_id).order_by(SourceFileRecord.source_type, SourceFileRecord.id)
        return list(self._session.scalars(statement))


class ConfigurationSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, run_id: uuid.UUID, config: ReconciliationConfig, *, settings: dict[str, Any] | None = None) -> ConfigurationSnapshotRecord:
        if self._session.scalar(select(ConfigurationSnapshotRecord.id).where(ConfigurationSnapshotRecord.run_id == run_id)) is not None:
            raise PersistenceConflictError(f"run {run_id} already has a configuration snapshot")
        values = {"maximum_group_size": config.maximum_group_size, **(settings or {})}
        record = ConfigurationSnapshotRecord(run_id=run_id, amount_tolerance=config.amount_tolerance, date_tolerance_days=config.date_tolerance_days, settings=values)
        self._session.add(record)
        self._session.flush()
        return record

    def get_for_run(self, run_id: uuid.UUID) -> ConfigurationSnapshotRecord:
        record = self._session.scalar(select(ConfigurationSnapshotRecord).where(ConfigurationSnapshotRecord.run_id == run_id))
        if record is None:
            raise RecordNotFoundError(f"configuration for run {run_id} was not found")
        return record


class ReconciliationResultRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_many(self, run_id: uuid.UUID, results: Iterable[ReconciliationResult]) -> list[ReconciliationResultRecord]:
        records = [self._to_record(run_id, result) for result in results]
        self._session.add_all(records)
        self._session.flush()
        return records

    def get(self, result_id: uuid.UUID, *, organization_id: uuid.UUID | None = None) -> ReconciliationResultRecord:
        statement = select(ReconciliationResultRecord).where(ReconciliationResultRecord.id == result_id)
        if organization_id is not None:
            statement = statement.join(ReconciliationRunRecord).where(
                ReconciliationRunRecord.organization_id == organization_id
            )
        record = self._session.scalar(statement)
        if record is None:
            raise RecordNotFoundError(f"reconciliation result {result_id} was not found")
        return record

    def list_for_run(self, run_id: uuid.UUID, *, page: Page = Page(), status: str | None = None, requires_review: bool | None = None) -> list[ReconciliationResultRecord]:
        statement = select(ReconciliationResultRecord).where(ReconciliationResultRecord.run_id == run_id)
        if status is not None:
            if status not in RESULT_STATUSES:
                raise ValueError("invalid reconciliation result status")
            statement = statement.where(ReconciliationResultRecord.status == status)
        if requires_review is not None:
            statement = statement.where(ReconciliationResultRecord.requires_review == requires_review)
        statement = statement.order_by(ReconciliationResultRecord.created_at, ReconciliationResultRecord.external_result_id).limit(page.limit).offset(page.offset)
        return list(self._session.scalars(statement))

    def count_for_run(self, run_id: uuid.UUID, *, status: str | None = None, requires_review: bool | None = None) -> int:
        statement = select(func.count()).select_from(ReconciliationResultRecord).where(ReconciliationResultRecord.run_id == run_id)
        if status is not None:
            if status not in RESULT_STATUSES:
                raise ValueError("invalid reconciliation result status")
            statement = statement.where(ReconciliationResultRecord.status == status)
        if requires_review is not None:
            statement = statement.where(ReconciliationResultRecord.requires_review == requires_review)
        return self._session.scalar(statement) or 0

    @staticmethod
    def _to_record(run_id: uuid.UUID, result: ReconciliationResult) -> ReconciliationResultRecord:
        return ReconciliationResultRecord(
            run_id=run_id,
            external_result_id=result.result_id,
            status=result.status.value,
            rule=result.rule,
            bank_source_record_ids=list(result.bank_source_record_ids),
            erp_invoice_ids=list(result.erp_invoice_ids),
            gateway_source_record_ids=list(result.gateway_source_record_ids),
            expected_amount=result.expected_amount,
            actual_amount=result.actual_amount,
            amount_difference=result.amount_difference,
            currency=result.currency,
            explanation=result.explanation,
            requires_review=result.requires_review,
        )


class AuditEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: AuditEvent) -> AuditEventRecord:
        try:
            run_id = uuid.UUID(event.run_id)
        except ValueError as error:
            raise ValueError("audit event run_id must be a UUID") from error
        # Lock the parent before calculating the next sequence to serialize writers.
        if self._session.scalar(select(ReconciliationRunRecord.id).where(ReconciliationRunRecord.id == run_id).with_for_update()) is None:
            raise RecordNotFoundError(f"reconciliation run {run_id} was not found")
        last_sequence = self._session.scalar(select(func.max(AuditEventRecord.sequence_number)).where(AuditEventRecord.run_id == run_id)) or 0
        record = AuditEventRecord(run_id=run_id, sequence_number=last_sequence + 1, event_type=event.event.value, occurred_at=_utc(datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))), details=dict(event.to_dict()["details"]))
        self._session.add(record)
        self._session.flush()
        return record

    def list_for_run(self, run_id: uuid.UUID, *, page: Page = Page()) -> list[AuditEventRecord]:
        statement = select(AuditEventRecord).where(AuditEventRecord.run_id == run_id).order_by(AuditEventRecord.sequence_number).limit(page.limit).offset(page.offset)
        return list(self._session.scalars(statement))

    def count_for_run(self, run_id: uuid.UUID) -> int:
        statement = select(func.count()).select_from(AuditEventRecord).where(AuditEventRecord.run_id == run_id)
        return self._session.scalar(statement) or 0


class SecurityAuditEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        organization_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        event_type: str,
        details: dict[str, Any] | None = None,
    ) -> SecurityAuditEventRecord:
        record = SecurityAuditEventRecord(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            details=dict(details or {}),
        )
        self._session.add(record)
        self._session.flush()
        return record

    def list_for_organization(
        self, organization_id: uuid.UUID, *, page: Page = Page()
    ) -> list[SecurityAuditEventRecord]:
        statement = (
            select(SecurityAuditEventRecord)
            .where(SecurityAuditEventRecord.organization_id == organization_id)
            .order_by(SecurityAuditEventRecord.occurred_at.desc(), SecurityAuditEventRecord.id.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        return list(self._session.scalars(statement))

    def count_for_organization(self, organization_id: uuid.UUID) -> int:
        return self._session.scalar(
            select(func.count()).select_from(SecurityAuditEventRecord).where(
                SecurityAuditEventRecord.organization_id == organization_id
            )
        ) or 0
