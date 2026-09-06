"""Focused SQLAlchemy repositories for ReconcileFlow persistence records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reconcileflow.audit import AuditEvent
from reconcileflow.reconciliation import ReconciliationConfig, ReconciliationResult

from .errors import InvalidStatusTransitionError, PersistenceConflictError, RecordNotFoundError
from .models import (
    AuditEventRecord,
    ConfigurationSnapshotRecord,
    OrganizationMembershipRecord,
    OrganizationRecord,
    ReconciliationResultRecord,
    ReconciliationRunRecord,
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

    def get_by_email(self, email: str) -> UserRecord | None:
        return self._session.scalar(select(UserRecord).where(UserRecord.email == email))

    def email_exists(self, email: str) -> bool:
        return self._session.scalar(select(UserRecord.id).where(UserRecord.email == email)) is not None


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


class ReconciliationRunRepository:
    _TRANSITIONS = {
        "PENDING": frozenset(("RUNNING", "FAILED")),
        "RUNNING": frozenset(("SUCCEEDED", "FAILED")),
        "SUCCEEDED": frozenset(),
        "FAILED": frozenset(),
    }

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, run_id: uuid.UUID | None = None) -> ReconciliationRunRecord:
        record = ReconciliationRunRecord(id=run_id or uuid.uuid4(), status="PENDING")
        self._session.add(record)
        self._session.flush()
        return record

    def get(self, run_id: uuid.UUID, *, lock: bool = False) -> ReconciliationRunRecord:
        statement = select(ReconciliationRunRecord).where(ReconciliationRunRecord.id == run_id)
        if lock:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        if record is None:
            raise RecordNotFoundError(f"reconciliation run {run_id} was not found")
        return record

    def list(self, *, page: Page = Page(), status: str | None = None) -> list[ReconciliationRunRecord]:
        statement = select(ReconciliationRunRecord)
        if status is not None:
            if status not in self._TRANSITIONS:
                raise ValueError("invalid reconciliation run status")
            statement = statement.where(ReconciliationRunRecord.status == status)
        statement = statement.order_by(ReconciliationRunRecord.created_at.desc(), ReconciliationRunRecord.id).limit(page.limit).offset(page.offset)
        return list(self._session.scalars(statement))

    def count(self, *, status: str | None = None) -> int:
        statement = select(func.count()).select_from(ReconciliationRunRecord)
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
    ) -> ReconciliationRunRecord:
        record = self.get(run_id, lock=True)
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

    def get(self, file_id: uuid.UUID) -> SourceFileRecord:
        record = self._session.get(SourceFileRecord, file_id)
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

    def get(self, result_id: uuid.UUID) -> ReconciliationResultRecord:
        record = self._session.get(ReconciliationResultRecord, result_id)
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
