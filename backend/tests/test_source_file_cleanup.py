from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from reconcileflow.maintenance import AbandonedUploadCleanup
from reconcileflow.persistence import Base, OrganizationRecord, PersistenceUnitOfWork
from reconcileflow.storage import LocalFileStorage


def test_abandoned_upload_cleanup_preserves_finalized_objects(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'cleanup.db').as_posix()}")
    Base.metadata.create_all(engine)
    organization_id = uuid.uuid4()
    prefix = hashlib.sha256(str(organization_id).encode()).hexdigest()[:16]
    abandoned_key = f"{prefix}-{'a' * 32}.csv"
    finalized_key = f"{prefix}-{'b' * 32}.csv"
    storage = LocalFileStorage(tmp_path / "objects", 1024)
    storage.directory.mkdir()
    for key in (abandoned_key, finalized_key):
        path = storage.directory / key
        path.write_text("id,amount\n1,10\n", encoding="utf-8")
        old = (datetime.now(UTC) - timedelta(hours=48)).timestamp()
        os.utime(path, (old, old))
    with Session(engine) as session:
        with PersistenceUnitOfWork(session) as work:
            session.add(OrganizationRecord(id=organization_id, name="Cleanup", slug="cleanup-files"))
            session.flush()
            run = work.runs.create(organization_id=organization_id)
            work.source_files.add(
                run_id=run.id, source_type="BANK_TRANSACTIONS",
                original_filename="bank.csv", checksum_sha256="0" * 64,
                size_bytes=17, content_type="text/csv", storage_key=finalized_key,
            )

    cleanup = AbandonedUploadCleanup(
        session_provider=lambda: Session(engine), storage=storage,
        retention_hours=24, batch_size=100,
    )
    preview = cleanup.run(dry_run=True)
    result = cleanup.run()

    assert (preview.eligible_objects, preview.deleted_objects) == (1, 0)
    assert (result.eligible_objects, result.deleted_objects) == (1, 1)
    assert not storage.exists(abandoned_key)
    assert storage.exists(finalized_key)
    engine.dispose()


def test_abandoned_upload_cleanup_rejects_naive_clock(tmp_path):
    storage = LocalFileStorage(tmp_path / "objects", 1024)
    cleanup = AbandonedUploadCleanup(
        session_provider=lambda: None, storage=storage,
        retention_hours=24, batch_size=100, clock=datetime.now,
    )
    try:
        cleanup.run()
    except ValueError as error:
        assert "timezone-aware" in str(error)
    else:
        raise AssertionError("naive cleanup clock was accepted")
