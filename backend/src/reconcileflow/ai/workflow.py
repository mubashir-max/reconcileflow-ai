"""Atomic orchestration for advisory AI match-suggestion generation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import uuid

from sqlalchemy.orm import Session

from reconcileflow.persistence.models import AIMatchSuggestionRecord
from reconcileflow.persistence.unit_of_work import PersistenceUnitOfWork

from .candidates import CandidateSourceRecord, GeneratedCandidate, ReconciliationCandidateGenerator
from .inference import (
    AIInferenceError,
    AIInferenceProvider,
    AIInferenceRequest,
    AIInferenceResponse,
)


class AIMatchSuggestionWorkflow:
    """Generate, validate, and atomically persist advisory suggestions."""

    def __init__(
        self, *, candidate_generator: ReconciliationCandidateGenerator,
        inference_provider: AIInferenceProvider, provider_name: str,
        prompt_version: str, inference_config_version: str,
        timeout_seconds: float, suggestion_ttl_days: int = 7,
    ) -> None:
        self._candidate_generator = candidate_generator
        self._inference_provider = inference_provider
        self._provider_name = _required_version(provider_name, "provider_name")
        self._prompt_version = _required_version(prompt_version, "prompt_version")
        self._inference_config_version = _required_version(
            inference_config_version, "inference_config_version"
        )
        if not 0.1 <= timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be between 0.1 and 120")
        if not 1 <= suggestion_ttl_days <= 90:
            raise ValueError("suggestion_ttl_days must be between 1 and 90")
        self._timeout_seconds = timeout_seconds
        self._suggestion_ttl_days = suggestion_ttl_days

    async def generate_and_persist(
        self, *, session: Session, organization_id: uuid.UUID, run_id: uuid.UUID,
        records: tuple[CandidateSourceRecord, ...],
        excluded_record_ids: frozenset[str] = frozenset(),
    ) -> tuple[AIMatchSuggestionRecord, ...]:
        candidates = self._candidate_generator.generate(
            organization_id=organization_id,
            run_id=run_id,
            records=records,
            excluded_record_ids=excluded_record_ids,
        )
        if not candidates:
            return ()
        request = AIInferenceRequest(
            features=tuple(candidate.features for candidate in candidates),
            prompt_version=self._prompt_version,
        )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                response = await self._inference_provider.infer(request)
        except TimeoutError as error:
            raise AIInferenceError("AI inference exceeded the configured timeout") from error
        validated = _map_response(response, candidates, self._prompt_version)

        expires_at = datetime.now(UTC) + timedelta(days=self._suggestion_ttl_days)
        persisted: list[AIMatchSuggestionRecord] = []
        with PersistenceUnitOfWork(session) as work:
            for candidate, suggestion in validated:
                features = candidate.features
                persisted.append(work.ai_match_suggestions.create(
                    organization_id=organization_id,
                    run_id=run_id,
                    candidates=candidate.records,
                    confidence_score=Decimal(str(suggestion.confidence)),
                    explanation={
                        "summary": suggestion.explanation,
                        "reason_codes": list(suggestion.reason_codes),
                    },
                    features={
                        "amount_similarity": features.amount_similarity,
                        "date_similarity": features.date_similarity,
                        "reference_similarity": features.reference_similarity,
                        "currency_matches": features.currency_matches,
                    },
                    provider=self._provider_name,
                    model_version=response.model_version,
                    prompt_template_version=response.prompt_version,
                    inference_config_version=self._inference_config_version,
                    expires_at=expires_at,
                ))
        return tuple(persisted)


def _map_response(
    response: AIInferenceResponse, candidates: tuple[GeneratedCandidate, ...], prompt_version: str,
):
    if response.prompt_version != prompt_version:
        raise AIInferenceError("AI inference returned incompatible version metadata")
    candidates_by_reference = {
        candidate.features.candidate_reference: candidate for candidate in candidates
    }
    mapped = []
    for suggestion in response.suggestions:
        candidate = candidates_by_reference.get(suggestion.candidate_reference)
        if candidate is None:
            raise AIInferenceError("AI inference returned an unknown candidate reference")
        mapped.append((candidate, suggestion))
    return tuple(mapped)


def _required_version(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 100:
        raise ValueError(f"{field} must be nonblank and at most 100 characters")
    return normalized
