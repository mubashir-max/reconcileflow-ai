"""Database infrastructure and persistent records for the ReconcileFlow API."""

from .base import Base
from .database import Database
from .dependencies import DatabaseDependency, SessionDependency, get_database, get_db_session
from .errors import InvalidStatusTransitionError, PersistenceConflictError, PersistenceError, RecordNotFoundError
from .models import (
    AuditEventRecord,
    ConfigurationSnapshotRecord,
    ReconciliationResultRecord,
    ReconciliationRunRecord,
    SourceFileRecord,
)
from .repositories import AuditEventRepository, ConfigurationSnapshotRepository, Page, ReconciliationResultRepository, ReconciliationRunRepository, SourceFileRepository
from .unit_of_work import PersistenceUnitOfWork

__all__ = [
    "AuditEventRecord",
    "AuditEventRepository",
    "Base",
    "ConfigurationSnapshotRecord",
    "ConfigurationSnapshotRepository",
    "Database",
    "DatabaseDependency",
    "InvalidStatusTransitionError",
    "Page",
    "PersistenceConflictError",
    "PersistenceError",
    "PersistenceUnitOfWork",
    "RecordNotFoundError",
    "ReconciliationResultRecord",
    "ReconciliationResultRepository",
    "ReconciliationRunRecord",
    "ReconciliationRunRepository",
    "SessionDependency",
    "SourceFileRecord",
    "SourceFileRepository",
    "get_database",
    "get_db_session",
]
