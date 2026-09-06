from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

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
        "organizations", "organization_memberships", "users",
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
