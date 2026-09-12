"""Privacy-safe lifecycle recording for AI inference operations."""
from __future__ import annotations
from contextlib import AbstractContextManager
from time import monotonic
from typing import Callable
import uuid
from datetime import UTC, datetime
from sqlalchemy.orm import Session
from reconcileflow.persistence import PersistenceUnitOfWork

class AIInferenceObserver:
    def __init__(self, *, session_provider: Callable[[], AbstractContextManager[Session]],
                 provider: str, model_version: str, prompt_version: str,
                 inference_config_version: str) -> None:
        self._sessions = session_provider
        self._provider = provider
        self._model = model_version
        self._prompt = prompt_version
        self._config = inference_config_version
        self._started: dict[uuid.UUID, float] = {}

    def start(self, *, organization_id: uuid.UUID, run_id: uuid.UUID, candidate_count: int) -> uuid.UUID:
        with self._sessions() as session, PersistenceUnitOfWork(session) as work:
            event = work.ai_inference_events.create(
                organization_id=organization_id, run_id=run_id, provider=self._provider,
                model_version=self._model, prompt_version=self._prompt,
                inference_config_version=self._config, candidate_count=candidate_count,
            )
        self._started[event.id] = monotonic()
        return event.id

    def complete(self, event_id: uuid.UUID, *, organization_id: uuid.UUID, outcome: str,
                 suggestion_count: int = 0, input_tokens: int = 0,
                 output_tokens: int = 0, error_code: str | None = None) -> None:
        started = self._started.pop(event_id, monotonic())
        duration_ms = max(0, round((monotonic() - started) * 1000))
        with self._sessions() as session, PersistenceUnitOfWork(session) as work:
            work.ai_inference_events.complete(
                event_id, organization_id=organization_id, outcome=outcome,
                suggestion_count=suggestion_count, input_tokens=input_tokens,
                output_tokens=output_tokens, duration_ms=duration_ms,
                error_code=error_code, completed_at=datetime.now(UTC),
            )
