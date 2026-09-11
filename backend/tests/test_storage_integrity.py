from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from reconcileflow.maintenance import StorageIntegrityVerifier
from reconcileflow.persistence import Base, OrganizationRecord, PersistenceUnitOfWork
from reconcileflow.storage import LocalFileStorage


def _key(organization_id: uuid.UUID, marker: str) -> str:
    prefix = hashlib.sha256(str(organization_id).encode()).hexdigest()[:16]
    return f"{prefix}-{marker * 32}.csv"


def test_storage_integrity_reports_safely_and_repairs_only_explicitly(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'integrity.db').as_posix()}")
    Base.metadata.create_all(engine)
    organization_id = uuid.uuid4()
    present_key = _key(organization_id, "a")
    missing_key = _key(organization_id, "b")
    abandoned_key = _key(organization_id, "c")
    content = b"id,amount\n1,10\n"
    storage = LocalFileStorage(tmp_path / "objects", 1024)
    storage.directory.mkdir()
    for key in (present_key, abandoned_key):
        path = storage.directory / key
        path.write_bytes(content)
        old = (datetime.now(UTC) - timedelta(hours=48)).timestamp()
        os.utime(path, (old, old))

    with Session(engine) as session:
        with PersistenceUnitOfWork(session) as work:
            session.add(OrganizationRecord(
                id=organization_id, name="Integrity", slug="integrity", storage_used_bytes=999
            ))
            session.flush()
            run = work.runs.create(organization_id=organization_id)
            work.source_files.add(
                run_id=run.id, source_type="BANK_TRANSACTIONS", original_filename="bank.csv",
                checksum_sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content) + 1,
                content_type="text/csv", storage_key=present_key,
            )
            work.source_files.add(
                run_id=run.id, source_type="ERP_INVOICES", original_filename="erp.csv",
                checksum_sha256="0" * 64, size_bytes=5, content_type="text/csv",
                storage_key=missing_key,
            )

    verifier = StorageIntegrityVerifier(
        session_provider=lambda: Session(engine), storage=storage,
        grace_hours=24, batch_size=100,
    )
    preview = verifier.run()
    assert (preview.checked_records, preview.missing_objects, preview.mismatched_objects) == (2, 1, 1)
    assert (preview.abandoned_objects, preview.usage_mismatches) == (1, 1)
    assert (preview.deleted_objects, preview.repaired_usage_counters, preview.repair) == (0, 0, False)
    assert storage.exists(abandoned_key)

    repaired = verifier.run(repair=True)
    assert (repaired.deleted_objects, repaired.repaired_usage_counters, repaired.repair) == (1, 1, True)
    assert not storage.exists(abandoned_key)
    assert storage.exists(present_key)
    with Session(engine) as session:
        organization = session.get(OrganizationRecord, organization_id)
        assert organization.storage_used_bytes == len(content) + 6
    engine.dispose()


def test_storage_integrity_rejects_naive_clock(tmp_path):
    verifier = StorageIntegrityVerifier(
        session_provider=lambda: None,
        storage=LocalFileStorage(tmp_path / "objects", 1024),
        grace_hours=24,
        batch_size=100,
        clock=datetime.now,
    )
    try:
        verifier.run()
    except ValueError as error:
        assert "timezone-aware" in str(error)
    else:
        raise AssertionError("naive verification clock was accepted")
