"""Atomic transaction boundary for related persistence operations."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .errors import PersistenceConflictError
from .repositories import AuditEventRepository, ConfigurationSnapshotRepository, ReconciliationResultRepository, ReconciliationRunRepository, SourceFileRepository


class PersistenceUnitOfWork:
    """Expose repositories that share one commit-or-rollback transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.runs = ReconciliationRunRepository(session)
        self.source_files = SourceFileRepository(session)
        self.configurations = ConfigurationSnapshotRepository(session)
        self.results = ReconciliationResultRepository(session)
        self.audit_events = AuditEventRepository(session)
        self._active = False

    def __enter__(self) -> PersistenceUnitOfWork:
        if self.session.in_transaction():
            raise RuntimeError("unit of work requires a session without an active transaction")
        self._active = True
        return self

    def __exit__(self, error_type: type[BaseException] | None, error: BaseException | None, traceback: TracebackType | None) -> bool:
        if error is None:
            try:
                self.session.commit()
            except IntegrityError as integrity_error:
                self.session.rollback()
                raise PersistenceConflictError("the database rejected conflicting persistence data") from integrity_error
        else:
            self.session.rollback()
            if isinstance(error, IntegrityError):
                raise PersistenceConflictError("the database rejected conflicting persistence data") from error
        self._active = False
        return False

    def rollback(self) -> None:
        self.session.rollback()
