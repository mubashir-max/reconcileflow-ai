"""Container health check for aggregate worker availability."""

from datetime import UTC, datetime, timedelta

from reconcileflow.api.config import APISettings
from reconcileflow.persistence import Database, PersistenceUnitOfWork


def main() -> None:
    settings = APISettings()
    database = Database(settings)
    try:
        with database.session() as session:
            active, _stale = PersistenceUnitOfWork(session).workers.health_counts(
                stale_before=datetime.now(UTC)
                - timedelta(seconds=settings.worker_health_stale_seconds)
            )
        raise SystemExit(0 if active else 1)
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
