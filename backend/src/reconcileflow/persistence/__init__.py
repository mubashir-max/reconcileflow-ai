"""Database infrastructure and persistent records for the ReconcileFlow API."""

from .base import Base
from .database import Database
from .dependencies import DatabaseDependency, SessionDependency, get_database, get_db_session
from .errors import InvalidStatusTransitionError, PersistenceConflictError, PersistenceError, RecordNotFoundError
from .models import (
    AuditEventRecord,
    ConfigurationSnapshotRecord,
    MEMBERSHIP_ROLES,
    OrganizationMembershipRecord,
    OrganizationRecord,
    ReconciliationResultRecord,
    ReconciliationRunRecord,
    RefreshTokenRecord,
    SecurityAuditEventRecord,
    SourceFileRecord,
    UserRecord,
)
from .repositories import (
    AuditEventRepository,
    ConfigurationSnapshotRepository,
    OrganizationMembershipRepository,
    OrganizationRepository,
    Page,
    ReconciliationResultRepository,
    ReconciliationRunRepository,
    RefreshTokenRepository,
    SecurityAuditEventRepository,
    SourceFileRepository,
    UserRepository,
)
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
    "MEMBERSHIP_ROLES",
    "OrganizationMembershipRecord",
    "OrganizationMembershipRepository",
    "OrganizationRecord",
    "OrganizationRepository",
    "Page",
    "PersistenceConflictError",
    "PersistenceError",
    "PersistenceUnitOfWork",
    "RecordNotFoundError",
    "ReconciliationResultRecord",
    "ReconciliationResultRepository",
    "ReconciliationRunRecord",
    "ReconciliationRunRepository",
    "RefreshTokenRecord",
    "RefreshTokenRepository",
    "SecurityAuditEventRecord",
    "SecurityAuditEventRepository",
    "SessionDependency",
    "SourceFileRecord",
    "SourceFileRepository",
    "UserRecord",
    "UserRepository",
    "get_database",
    "get_db_session",
]
