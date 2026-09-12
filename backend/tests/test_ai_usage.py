from contextlib import contextmanager
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from reconcileflow.ai.usage import AIUsageController, AIUsageLimitError
from reconcileflow.persistence import Base
from reconcileflow.persistence.models import AIUsageRecord, OrganizationRecord, ReconciliationRunRecord


@pytest.fixture
def usage_foundation(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'usage.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def sessions():
        with factory() as session:
            yield session

    organization_id, run_id = uuid.uuid4(), uuid.uuid4()
    with sessions() as session:
        session.add(OrganizationRecord(
            id=organization_id, name="Metered AI", slug=f"metered-{organization_id.hex}",
            hosted_ai_enabled=True, ai_daily_request_limit=2,
            ai_monthly_request_limit=3, ai_daily_token_limit=1000,
            ai_monthly_token_limit=2000,
        ))
        session.add(ReconciliationRunRecord(id=run_id, organization_id=organization_id))
        session.commit()
    yield sessions, organization_id, run_id
    engine.dispose()


def _controller(sessions, *, provider="openai-compatible"):
    return AIUsageController(
        session_provider=sessions, provider_name=provider,
        model_version="hosted-v1", estimated_tokens_per_candidate=100,
    )


def test_hosted_usage_is_reserved_finalized_and_aggregated(usage_foundation):
    sessions, organization_id, run_id = usage_foundation
    controller = _controller(sessions)
    reservation_id = controller.reserve(
        organization_id=organization_id, run_id=run_id, candidate_count=2,
    )
    assert reservation_id is not None
    assert controller.summary(organization_id).daily_tokens == 200

    controller.finalize(
        reservation_id, organization_id=organization_id,
        input_tokens=40, output_tokens=10,
    )
    summary = controller.summary(organization_id)
    assert (summary.daily_requests, summary.daily_tokens) == (1, 50)
    with sessions() as session:
        record = session.scalar(select(AIUsageRecord))
        assert record.status == "FINALIZED"
        assert not hasattr(record, "prompt")


def test_disabled_and_exhausted_organizations_are_rejected_before_spend(usage_foundation):
    sessions, organization_id, run_id = usage_foundation
    controller = _controller(sessions)
    for _ in range(2):
        reservation = controller.reserve(
            organization_id=organization_id, run_id=run_id, candidate_count=1,
        )
        controller.finalize(
            reservation, organization_id=organization_id, input_tokens=50, output_tokens=10,
        )
    with pytest.raises(AIUsageLimitError, match="limit"):
        controller.reserve(organization_id=organization_id, run_id=run_id, candidate_count=1)

    with sessions() as session:
        organization = session.get(OrganizationRecord, organization_id)
        organization.hosted_ai_enabled = False
        session.commit()
    with pytest.raises(AIUsageLimitError, match="not enabled"):
        controller.reserve(organization_id=organization_id, run_id=run_id, candidate_count=1)


def test_failed_calls_release_quota_and_local_providers_are_unmetered(usage_foundation):
    sessions, organization_id, run_id = usage_foundation
    controller = _controller(sessions)
    reservation = controller.reserve(
        organization_id=organization_id, run_id=run_id, candidate_count=2,
    )
    controller.release(reservation, organization_id=organization_id)
    assert controller.summary(organization_id).daily_requests == 0
    assert _controller(sessions, provider="deterministic").reserve(
        organization_id=organization_id, run_id=run_id, candidate_count=2,
    ) is None
