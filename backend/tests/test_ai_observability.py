from contextlib import contextmanager
import uuid
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from reconcileflow.ai.observability import AIInferenceObserver
from reconcileflow.persistence import Base
from reconcileflow.persistence.models import AIInferenceEventRecord, OrganizationRecord, ReconciliationRunRecord


def test_observer_records_only_privacy_safe_aggregate_metadata(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'events.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def sessions():
        with factory() as session:
            yield session

    organization_id, run_id = uuid.uuid4(), uuid.uuid4()
    with sessions() as session:
        session.add(OrganizationRecord(id=organization_id, name="Observed", slug=f"observed-{organization_id.hex}"))
        session.add(ReconciliationRunRecord(id=run_id, organization_id=organization_id))
        session.commit()

    observer = AIInferenceObserver(
        session_provider=sessions, provider="openai-compatible", model_version="model-v1",
        prompt_version="prompt-v1", inference_config_version="config-v1",
    )
    event_id = observer.start(organization_id=organization_id, run_id=run_id, candidate_count=4)
    observer.complete(event_id, organization_id=organization_id, outcome="SUCCEEDED",
                      suggestion_count=2, input_tokens=40, output_tokens=10)

    with Session(engine) as session:
        event = session.scalar(select(AIInferenceEventRecord))
        assert (event.outcome, event.candidate_count, event.suggestion_count) == ("SUCCEEDED", 4, 2)
        assert (event.input_tokens, event.output_tokens) == (40, 10)
        forbidden = {"prompt", "response", "credential", "api_key", "candidate_ids"}
        assert forbidden.isdisjoint(AIInferenceEventRecord.__table__.columns.keys())
    engine.dispose()
