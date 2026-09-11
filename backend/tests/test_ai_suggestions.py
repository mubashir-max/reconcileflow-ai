from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from reconcileflow.ai import CandidateRecordSet, MatchSuggestionStatus
from reconcileflow.persistence import (
    AIMatchSuggestionRecord,
    Base,
    OrganizationRecord,
    PersistenceConflictError,
    PersistenceUnitOfWork,
    ReconciliationResultRecord,
    RecordNotFoundError,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session
    engine.dispose()


def _foundation(session: Session):
    organization_id = uuid.uuid4()
    with PersistenceUnitOfWork(session) as work:
        session.add(OrganizationRecord(id=organization_id, name="AI Review", slug=f"ai-{organization_id.hex}"))
        session.flush()
        user = work.users.create(email=f"{organization_id.hex}@example.com", password_hash="safe-test-hash")
        run = work.runs.create(organization_id=organization_id)
    return organization_id, user.id, run.id


def _create(session: Session, organization_id: uuid.UUID, run_id: uuid.UUID):
    with PersistenceUnitOfWork(session) as work:
        return work.ai_match_suggestions.create(
            organization_id=organization_id,
            run_id=run_id,
            candidates=CandidateRecordSet(
                bank_record_ids=("BANK-001",), erp_invoice_ids=("INV-001",)
            ),
            confidence_score=Decimal("0.8750"),
            explanation={"summary": "Reference and amount signals agree.", "reason_codes": ["REFERENCE_MATCH"]},
            features={"amount_delta": 0, "date_delta_days": 1, "currency_equal": True},
            provider="deterministic-test-provider",
            model_version="test-v1",
            prompt_template_version="suggestion-v1",
            inference_config_version="config-v1",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )


def test_candidate_record_set_validates_internal_identifiers():
    with pytest.raises(ValueError, match="at least one"):
        CandidateRecordSet()
    with pytest.raises(ValueError, match="unique"):
        CandidateRecordSet(bank_record_ids=("BANK-1", "BANK-1"))


def test_repository_creates_lists_and_resolves_advisory_suggestion(session: Session):
    organization_id, reviewer_id, run_id = _foundation(session)
    suggestion = _create(session, organization_id, run_id)

    listed = PersistenceUnitOfWork(session).ai_match_suggestions.list_for_run(
        run_id, organization_id=organization_id, status=MatchSuggestionStatus.PENDING
    )
    assert [record.id for record in listed] == [suggestion.id]
    assert suggestion.confidence_score == Decimal("0.8750")
    assert suggestion.explanation["reason_codes"] == ["REFERENCE_MATCH"]
    assert session.scalar(select(func.count()).select_from(ReconciliationResultRecord)) == 0
    session.rollback()

    with PersistenceUnitOfWork(session) as work:
        resolved = work.ai_match_suggestions.resolve(
            suggestion.id, organization_id=organization_id,
            reviewer_user_id=reviewer_id, decision=MatchSuggestionStatus.ACCEPTED,
            reviewed_at=datetime.now(UTC),
        )
    assert resolved.status == "ACCEPTED"
    assert resolved.reviewed_by_user_id == reviewer_id
    assert session.scalar(select(func.count()).select_from(ReconciliationResultRecord)) == 0
    session.rollback()
    with pytest.raises(PersistenceConflictError, match="no longer pending"):
        with PersistenceUnitOfWork(session) as work:
            work.ai_match_suggestions.resolve(
                suggestion.id, organization_id=organization_id,
                reviewer_user_id=reviewer_id, decision="REJECTED", reviewed_at=datetime.now(UTC),
            )


def test_repository_hides_cross_tenant_suggestions(session: Session):
    organization_id, _, run_id = _foundation(session)
    other_organization_id, _, _ = _foundation(session)
    suggestion = _create(session, organization_id, run_id)
    with pytest.raises(RecordNotFoundError, match=str(suggestion.id)):
        PersistenceUnitOfWork(session).ai_match_suggestions.get(
            suggestion.id, organization_id=other_organization_id
        )


def test_repository_rejects_sensitive_metadata_and_duplicate_candidates(session: Session):
    organization_id, _, run_id = _foundation(session)
    _create(session, organization_id, run_id)
    with pytest.raises(PersistenceConflictError):
        _create(session, organization_id, run_id)

    with pytest.raises(ValueError, match="forbidden"):
        with PersistenceUnitOfWork(session) as work:
            work.ai_match_suggestions.create(
                organization_id=organization_id,
                run_id=run_id,
                candidates=CandidateRecordSet(bank_record_ids=("BANK-002",)),
                confidence_score=Decimal("0.5"),
                explanation={"raw_prompt": "sensitive"},
                features={"amount_delta": 0},
                provider="test", model_version="v1",
                prompt_template_version="v1", inference_config_version="v1",
            )


def test_database_constraints_reject_invalid_confidence(session: Session):
    organization_id, _, run_id = _foundation(session)
    session.add(AIMatchSuggestionRecord(
        organization_id=organization_id, run_id=run_id, status="PENDING",
        confidence_score=Decimal("1.5"), candidate_fingerprint="a" * 64,
        bank_record_ids=["BANK-001"], erp_invoice_ids=[], gateway_record_ids=[],
        explanation={"summary": "safe"}, features={"score": 1}, provider="test",
        model_version="v1", prompt_template_version="v1", inference_config_version="v1",
    ))
    with pytest.raises(Exception):
        session.commit()
    session.rollback()
