from datetime import date
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from reconcileflow.ai import (
    AIInferenceError,
    AIInferenceResponse,
    AIInferenceSuggestion,
    CandidateSourceRecord,
    CandidateSourceType,
    DeterministicAIInferenceProvider,
    ReconciliationCandidateGenerator,
)
from reconcileflow.ai.workflow import AIMatchSuggestionWorkflow
from reconcileflow.persistence import (
    AIMatchSuggestionRecord,
    Base,
    OrganizationRecord,
    PersistenceConflictError,
    ReconciliationResultRecord,
    ReconciliationRunRecord,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session
    engine.dispose()


def _foundation(session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    organization_id = uuid.uuid4()
    run_id = uuid.uuid4()
    session.add(OrganizationRecord(
        id=organization_id, name="AI Workflow", slug=f"ai-{organization_id.hex}"
    ))
    session.add(ReconciliationRunRecord(id=run_id, organization_id=organization_id))
    session.commit()
    return organization_id, run_id


def _records(organization_id: uuid.UUID, run_id: uuid.UUID):
    common = dict(
        organization_id=organization_id, run_id=run_id,
        amount=Decimal("100"), effective_date=date(2026, 1, 1), currency="USD",
    )
    return (
        CandidateSourceRecord(
            source_type=CandidateSourceType.BANK, record_id="bank-1",
            references=("INV-1",), **common,
        ),
        CandidateSourceRecord(
            source_type=CandidateSourceType.ERP, record_id="invoice-1",
            references=("inv1",), **common,
        ),
    )


def _workflow(provider) -> AIMatchSuggestionWorkflow:
    return AIMatchSuggestionWorkflow(
        candidate_generator=ReconciliationCandidateGenerator(),
        inference_provider=provider,
        provider_name="deterministic",
        prompt_version="prompt-v1",
        inference_config_version="config-v1",
        timeout_seconds=1,
    )


@pytest.mark.anyio
async def test_workflow_generates_and_atomically_persists_advisory_suggestions(session: Session):
    organization_id, run_id = _foundation(session)
    provider = DeterministicAIInferenceProvider(
        model_version="local-v1", max_candidates=10, max_suggestions=10
    )
    suggestions = await _workflow(provider).generate_and_persist(
        session=session, organization_id=organization_id, run_id=run_id,
        records=_records(organization_id, run_id),
    )
    assert len(suggestions) == 1
    assert suggestions[0].status == "PENDING"
    assert suggestions[0].model_version == "local-v1"
    assert suggestions[0].features == {
        "amount_similarity": 1.0,
        "date_similarity": 1.0,
        "reference_similarity": 1.0,
        "currency_matches": True,
    }
    assert session.scalar(select(func.count()).select_from(ReconciliationResultRecord)) == 0


class UnknownCandidateProvider:
    async def infer(self, request):
        return AIInferenceResponse(
            suggestions=(AIInferenceSuggestion(
                candidate_reference="candidate-not-submitted", confidence=0.9,
                reason_codes=("UNKNOWN",), explanation="Invalid provider candidate.",
            ),),
            model_version="test-v1", prompt_version=request.prompt_version,
        )


@pytest.mark.anyio
async def test_unknown_provider_candidate_is_rejected_without_persistence(session: Session):
    organization_id, run_id = _foundation(session)
    with pytest.raises(AIInferenceError, match="unknown candidate"):
        await _workflow(UnknownCandidateProvider()).generate_and_persist(
            session=session, organization_id=organization_id, run_id=run_id,
            records=_records(organization_id, run_id),
        )
    assert session.scalar(select(func.count()).select_from(AIMatchSuggestionRecord)) == 0


class FailedProvider:
    async def infer(self, request):
        del request
        raise AIInferenceError("sanitized provider failure")


@pytest.mark.anyio
async def test_provider_failure_does_not_persist_partial_state(session: Session):
    organization_id, run_id = _foundation(session)
    with pytest.raises(AIInferenceError, match="sanitized provider failure"):
        await _workflow(FailedProvider()).generate_and_persist(
            session=session, organization_id=organization_id, run_id=run_id,
            records=_records(organization_id, run_id),
        )
    assert session.scalar(select(func.count()).select_from(AIMatchSuggestionRecord)) == 0


@pytest.mark.anyio
async def test_duplicate_suggestion_is_rejected_and_existing_record_is_preserved(session: Session):
    organization_id, run_id = _foundation(session)
    workflow = _workflow(DeterministicAIInferenceProvider(
        model_version="local-v1", max_candidates=10, max_suggestions=10
    ))
    values = dict(
        session=session, organization_id=organization_id, run_id=run_id,
        records=_records(organization_id, run_id),
    )
    await workflow.generate_and_persist(**values)
    with pytest.raises(PersistenceConflictError):
        await workflow.generate_and_persist(**values)
    assert session.scalar(select(func.count()).select_from(AIMatchSuggestionRecord)) == 1


class SlowProvider:
    async def infer(self, request):
        import asyncio
        del request
        await asyncio.sleep(1)


@pytest.mark.anyio
async def test_timeout_is_sanitized_and_does_not_persist(session: Session):
    organization_id, run_id = _foundation(session)
    workflow = AIMatchSuggestionWorkflow(
        candidate_generator=ReconciliationCandidateGenerator(),
        inference_provider=SlowProvider(), provider_name="slow",
        prompt_version="prompt-v1", inference_config_version="config-v1",
        timeout_seconds=0.1,
    )
    with pytest.raises(AIInferenceError, match="configured timeout"):
        await workflow.generate_and_persist(
            session=session, organization_id=organization_id, run_id=run_id,
            records=_records(organization_id, run_id),
        )
    assert session.scalar(select(func.count()).select_from(AIMatchSuggestionRecord)) == 0
