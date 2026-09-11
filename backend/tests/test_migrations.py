from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[2]


def _config(database_url: str) -> Config:
    config = Config(ROOT / "alembic.ini")
    config.attributes["database_url"] = database_url
    return config


def test_initial_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database_path = tmp_path / "migration-test.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert set(inspect(engine).get_table_names()) == {
        "alembic_version", "audit_events", "configuration_snapshots",
        "reconciliation_results", "reconciliation_runs", "source_files",
        "organizations", "organization_memberships", "users", "refresh_tokens",
        "security_audit_events", "background_jobs", "workers",
    }
    engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(database_url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_v02_database_can_upgrade_and_rollback_identity_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "v02-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)

    command.upgrade(config, "7da9a8e2e1ef")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert {"organizations", "users", "organization_memberships"} <= set(
        inspect(engine).get_table_names()
    )
    engine.dispose()

    command.downgrade(config, "7da9a8e2e1ef")
    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert not {"organizations", "users", "organization_memberships"} & tables
    assert "reconciliation_runs" in tables
    engine.dispose()


def test_identity_database_can_add_and_remove_refresh_sessions(tmp_path: Path) -> None:
    database_path = tmp_path / "token-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)

    command.upgrade(config, "c31b8e4d9a72")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert "refresh_tokens" in inspect(engine).get_table_names()
    engine.dispose()

    command.downgrade(config, "c31b8e4d9a72")
    engine = create_engine(database_url)
    tables = inspect(engine).get_table_names()
    assert "refresh_tokens" not in tables
    assert "users" in tables
    engine.dispose()


def test_token_database_can_add_and_remove_security_audit_events(tmp_path: Path) -> None:
    database_path = tmp_path / "security-audit-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)

    command.upgrade(config, "e8f4c2a91d63")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert "security_audit_events" in inspect(engine).get_table_names()
    engine.dispose()

    command.downgrade(config, "e8f4c2a91d63")
    engine = create_engine(database_url)
    assert "security_audit_events" not in inspect(engine).get_table_names()
    engine.dispose()


def test_security_audit_database_can_add_and_remove_login_protection(tmp_path: Path) -> None:
    database_path = tmp_path / "login-protection-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)

    command.upgrade(config, "f3a7b91c4d20")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert {"failed_login_attempts", "locked_until"} <= columns
    engine.dispose()

    command.downgrade(config, "f3a7b91c4d20")
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert not {"failed_login_attempts", "locked_until"} & columns
    engine.dispose()


def test_login_protection_database_can_add_and_remove_background_jobs(tmp_path: Path) -> None:
    database_path = tmp_path / "background-jobs-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)

    command.upgrade(config, "a4c8d2e71f50")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "background_jobs" in inspector.get_table_names()
    assert {
        "organization_id", "run_id", "status", "progress_percentage",
        "attempt_count", "max_attempts", "scheduled_at", "retry_at",
        "claimed_by", "heartbeat_at",
    } <= {column["name"] for column in inspector.get_columns("background_jobs")}
    engine.dispose()

    command.downgrade(config, "a4c8d2e71f50")
    engine = create_engine(database_url)
    assert "background_jobs" not in inspect(engine).get_table_names()
    engine.dispose()


def test_background_jobs_can_add_and_remove_worker_leases(tmp_path: Path) -> None:
    database_path = tmp_path / "worker-leases-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)

    command.upgrade(config, "d5e9a7c31b42")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("background_jobs")}
    assert {"claimed_by", "heartbeat_at"} <= columns
    engine.dispose()

    command.downgrade(config, "d5e9a7c31b42")
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("background_jobs")}
    assert not {"claimed_by", "heartbeat_at"} & columns
    engine.dispose()


def test_worker_leases_can_add_and_remove_manual_retry_tracking(tmp_path: Path) -> None:
    database_path = tmp_path / "manual-retries-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)

    command.upgrade(config, "e6f1c8b42a73")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("background_jobs")}
    assert {"total_attempt_count", "manual_retry_count", "last_manual_retry_at"} <= columns
    engine.dispose()

    command.downgrade(config, "e6f1c8b42a73")
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("background_jobs")}
    assert not {"total_attempt_count", "manual_retry_count", "last_manual_retry_at"} & columns
    engine.dispose()


def test_manual_retries_can_add_and_remove_worker_lifecycle(tmp_path: Path) -> None:
    database_path = tmp_path / "worker-lifecycle-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)
    command.upgrade(config, "f7b3c9d42e61")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert "workers" in inspect(engine).get_table_names()
    assert {"worker_id", "status", "started_at", "heartbeat_at", "stopped_at"} <= {
        column["name"] for column in inspect(engine).get_columns("workers")
    }
    engine.dispose()
    command.downgrade(config, "f7b3c9d42e61")
    engine = create_engine(database_url)
    assert "workers" not in inspect(engine).get_table_names()
    engine.dispose()


def test_worker_lifecycle_can_add_and_remove_retention_indexes(tmp_path: Path) -> None:
    database_path = tmp_path / "retention-indexes-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)
    command.upgrade(config, "a8c4d1e72f90")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert "ix_background_jobs_terminal_completed" in {
        index["name"] for index in inspect(engine).get_indexes("background_jobs")
    }
    assert "ix_workers_status_stopped" in {
        index["name"] for index in inspect(engine).get_indexes("workers")
    }
    engine.dispose()
    command.downgrade(config, "a8c4d1e72f90")
    engine = create_engine(database_url)
    assert "ix_background_jobs_terminal_completed" not in {
        index["name"] for index in inspect(engine).get_indexes("background_jobs")
    }
    assert "ix_workers_status_stopped" not in {
        index["name"] for index in inspect(engine).get_indexes("workers")
    }
    engine.dispose()


def test_retention_schema_can_add_and_remove_job_deadlines(tmp_path: Path) -> None:
    database_path = tmp_path / "job-deadlines-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)
    command.upgrade(config, "c9d2e6f41a83")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("background_jobs")}
    assert {"timeout_seconds", "deadline_at"} <= columns
    engine.dispose()
    command.downgrade(config, "c9d2e6f41a83")
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("background_jobs")}
    assert not {"timeout_seconds", "deadline_at"} & columns
    engine.dispose()


def test_job_deadlines_can_add_and_remove_priorities(tmp_path: Path) -> None:
    database_path = tmp_path / "job-priorities-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)
    command.upgrade(config, "b7e3f9a21c64")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "priority" in {
        column["name"] for column in inspector.get_columns("background_jobs")
    }
    queue_index = next(
        index for index in inspector.get_indexes("background_jobs")
        if index["name"] == "ix_background_jobs_queue"
    )
    assert queue_index["column_names"] == [
        "status", "priority", "scheduled_at", "retry_at", "created_at"
    ]
    engine.dispose()
    command.downgrade(config, "b7e3f9a21c64")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "priority" not in {
        column["name"] for column in inspector.get_columns("background_jobs")
    }
    queue_index = next(
        index for index in inspector.get_indexes("background_jobs")
        if index["name"] == "ix_background_jobs_queue"
    )
    assert queue_index["column_names"] == [
        "status", "scheduled_at", "retry_at", "created_at"
    ]
    engine.dispose()

def test_existing_runs_are_assigned_to_legacy_organization(tmp_path: Path) -> None:
    database_path = tmp_path / "tenant-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = _config(database_url)
    command.upgrade(config, "e8f4c2a91d63")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO reconciliation_runs (id, status) VALUES (:id, 'PENDING')"), {"id": "20000000000000000000000000000001"})
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        organization_id = connection.scalar(text("SELECT organization_id FROM reconciliation_runs"))
        legacy_slug = connection.scalar(text("SELECT slug FROM organizations WHERE id = :id"), {"id": organization_id})
    assert organization_id is not None
    assert legacy_slug == "legacy-workspace"
    engine.dispose()
