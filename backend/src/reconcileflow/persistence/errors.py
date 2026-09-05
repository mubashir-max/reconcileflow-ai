"""Safe persistence-layer errors that do not reveal database internals."""


class PersistenceError(Exception):
    """Base class for errors callers may safely handle."""


class RecordNotFoundError(PersistenceError):
    """Raised when a requested persistence record does not exist."""


class PersistenceConflictError(PersistenceError):
    """Raised when a uniqueness or consistency rule is violated."""


class InvalidStatusTransitionError(PersistenceError):
    """Raised when a reconciliation run cannot enter the requested state."""
