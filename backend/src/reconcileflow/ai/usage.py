"""Organization-scoped reservation and metering for hosted AI inference."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable
import uuid

from sqlalchemy.orm import Session

from reconcileflow.persistence.unit_of_work import PersistenceUnitOfWork

from .inference import AIInferenceError


class AIUsageLimitError(AIInferenceError):
    """Hosted inference is disabled or an organization quota is exhausted."""


@dataclass(frozen=True, slots=True)
class AIUsageSummary:
    daily_requests: int
    daily_tokens: int
    monthly_requests: int
    monthly_tokens: int


class AIUsageController:
    """Reserve capacity before a paid call and finalize only aggregate usage."""

    def __init__(
        self, *, session_provider: Callable[[], AbstractContextManager[Session]],
        provider_name: str, model_version: str,
        estimated_tokens_per_candidate: int = 256,
        reservation_ttl_seconds: int = 300,
    ) -> None:
        if estimated_tokens_per_candidate < 1:
            raise ValueError("estimated_tokens_per_candidate must be positive")
        if reservation_ttl_seconds < 30:
            raise ValueError("reservation_ttl_seconds must be at least 30")
        self._session_provider = session_provider
        self._provider_name = provider_name
        self._model_version = model_version
        self._estimated_tokens_per_candidate = estimated_tokens_per_candidate
        self._reservation_ttl_seconds = reservation_ttl_seconds

    @property
    def is_metered(self) -> bool:
        return self._provider_name == "openai-compatible"

    def reserve(self, *, organization_id: uuid.UUID, run_id: uuid.UUID, candidate_count: int) -> uuid.UUID | None:
        if not self.is_metered:
            return None
        if candidate_count < 1:
            raise ValueError("candidate_count must be positive")
        now = datetime.now(UTC)
        estimated_tokens = candidate_count * self._estimated_tokens_per_candidate
        with self._session_provider() as session, PersistenceUnitOfWork(session) as work:
            organization = work.organizations.get(organization_id, lock=True)
            if not organization.hosted_ai_enabled:
                raise AIUsageLimitError("hosted AI inference is not enabled for this organization")
            work.ai_usage.release_expired(organization_id=organization_id, now=now)
            usage = self._summarize(work, organization_id, now)
            if (
                usage.daily_requests + 1 > organization.ai_daily_request_limit
                or usage.monthly_requests + 1 > organization.ai_monthly_request_limit
                or usage.daily_tokens + estimated_tokens > organization.ai_daily_token_limit
                or usage.monthly_tokens + estimated_tokens > organization.ai_monthly_token_limit
            ):
                raise AIUsageLimitError("hosted AI usage limit has been reached")
            return work.ai_usage.reserve(
                organization_id=organization_id, run_id=run_id,
                provider=self._provider_name, model_version=self._model_version,
                reserved_tokens=estimated_tokens, candidate_count=candidate_count,
                expires_at=now + timedelta(seconds=self._reservation_ttl_seconds),
            ).id

    def finalize(self, reservation_id: uuid.UUID, *, organization_id: uuid.UUID, input_tokens: int, output_tokens: int) -> None:
        with self._session_provider() as session, PersistenceUnitOfWork(session) as work:
            work.ai_usage.finalize(
                reservation_id, organization_id=organization_id,
                input_tokens=input_tokens, output_tokens=output_tokens,
                finalized_at=datetime.now(UTC),
            )

    def release(self, reservation_id: uuid.UUID, *, organization_id: uuid.UUID) -> None:
        with self._session_provider() as session, PersistenceUnitOfWork(session) as work:
            work.ai_usage.release(
                reservation_id, organization_id=organization_id,
                released_at=datetime.now(UTC),
            )

    def summary(self, organization_id: uuid.UUID) -> AIUsageSummary:
        now = datetime.now(UTC)
        with self._session_provider() as session, PersistenceUnitOfWork(session) as work:
            work.organizations.get(organization_id)
            work.ai_usage.release_expired(organization_id=organization_id, now=now)
            return self._summarize(work, organization_id, now)

    @staticmethod
    def _summarize(work: PersistenceUnitOfWork, organization_id: uuid.UUID, now: datetime) -> AIUsageSummary:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        daily_requests, daily_tokens = work.ai_usage.summarize(
            organization_id=organization_id, since=day_start, now=now,
        )
        monthly_requests, monthly_tokens = work.ai_usage.summarize(
            organization_id=organization_id, since=month_start, now=now,
        )
        return AIUsageSummary(daily_requests, daily_tokens, monthly_requests, monthly_tokens)
