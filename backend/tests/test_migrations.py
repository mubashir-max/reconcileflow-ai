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
        "security_audit_events", "background_jobs",
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
