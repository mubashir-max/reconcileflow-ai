"""Provider-independent, privacy-minimizing AI inference contract."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import re
from typing import Protocol, runtime_checkable


class AIInferenceError(RuntimeError):
    """Safe public failure raised by an inference provider."""


class AIInferenceDisabledError(AIInferenceError):
    """Raised when advisory inference has not been enabled."""


class AIInferenceResponseError(AIInferenceError):
    """Raised when a provider produces invalid structured output."""


@dataclass(frozen=True, slots=True)
class NormalizedMatchFeatures:
    """Minimized derived features; source records and business text are excluded."""

    candidate_reference: str
    amount_similarity: float
    date_similarity: float
    reference_similarity: float
    currency_matches: bool

    def __post_init__(self) -> None:
        reference = self.candidate_reference.strip()
        if not reference or len(reference) > 200:
            raise ValueError("candidate_reference must be nonblank and at most 200 characters")
        object.__setattr__(self, "candidate_reference", reference)
        for name in ("amount_similarity", "date_similarity", "reference_similarity"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a finite number between 0 and 1")


@dataclass(frozen=True, slots=True)
class AIInferenceRequest:
    features: tuple[NormalizedMatchFeatures, ...]
    prompt_version: str

    def __post_init__(self) -> None:
        if not self.features:
            raise ValueError("at least one candidate feature set is required")
        if len({item.candidate_reference for item in self.features}) != len(self.features):
            raise ValueError("candidate references must be unique")
        prompt_version = self.prompt_version.strip()
        if not prompt_version or len(prompt_version) > 100:
            raise ValueError("prompt_version must be nonblank and at most 100 characters")
        object.__setattr__(self, "prompt_version", prompt_version)


@dataclass(frozen=True, slots=True)
class AIInferenceSuggestion:
    candidate_reference: str
    confidence: float
    reason_codes: tuple[str, ...]
    explanation: str

    def __post_init__(self) -> None:
        reference = self.candidate_reference.strip()
        explanation = self.explanation.strip()
        if not reference or len(reference) > 200:
            raise AIInferenceResponseError("inference provider returned an invalid response")
        if isinstance(self.confidence, bool) or not isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise AIInferenceResponseError("inference provider returned an invalid response")
        if not explanation or len(explanation) > 500:
            raise AIInferenceResponseError("inference provider returned an invalid response")
        if not self.reason_codes or len(self.reason_codes) > 10 or any(
            not re.fullmatch(r"[A-Z][A-Z0-9_]{0,49}", code) for code in self.reason_codes
        ):
            raise AIInferenceResponseError("inference provider returned an invalid response")
        object.__setattr__(self, "candidate_reference", reference)
        object.__setattr__(self, "explanation", explanation)


@dataclass(frozen=True, slots=True)
class AIInferenceResponse:
    suggestions: tuple[AIInferenceSuggestion, ...]
    model_version: str
    prompt_version: str

    def __post_init__(self) -> None:
        if not self.model_version.strip() or len(self.model_version) > 100:
            raise AIInferenceResponseError("inference provider returned an invalid response")
        if not self.prompt_version.strip() or len(self.prompt_version) > 100:
            raise AIInferenceResponseError("inference provider returned an invalid response")
        references = [item.candidate_reference for item in self.suggestions]
        if len(references) != len(set(references)):
            raise AIInferenceResponseError("inference provider returned an invalid response")


@runtime_checkable
class AIInferenceProvider(Protocol):
    async def infer(self, request: AIInferenceRequest) -> AIInferenceResponse: ...


class DisabledAIInferenceProvider:
    async def infer(self, request: AIInferenceRequest) -> AIInferenceResponse:
        del request
        raise AIInferenceDisabledError("AI-assisted matching is not enabled")


class DeterministicAIInferenceProvider:
    """Local provider for development and CI; performs no network or database I/O."""

    def __init__(self, *, model_version: str, max_candidates: int, max_suggestions: int) -> None:
        self._model_version = model_version
        self._max_candidates = max_candidates
        self._max_suggestions = max_suggestions

    async def infer(self, request: AIInferenceRequest) -> AIInferenceResponse:
        if len(request.features) > self._max_candidates:
            raise AIInferenceError("inference request exceeds the configured candidate limit")
        ranked: list[AIInferenceSuggestion] = []
        for item in request.features:
            confidence = round(
                item.amount_similarity * 0.45
                + item.date_similarity * 0.25
                + item.reference_similarity * 0.25
                + (0.05 if item.currency_matches else 0.0),
                6,
            )
            reasons = tuple(
                code for code, matched in (
                    ("AMOUNT_SIMILAR", item.amount_similarity >= 0.8),
                    ("DATE_SIMILAR", item.date_similarity >= 0.8),
                    ("REFERENCE_SIMILAR", item.reference_similarity >= 0.8),
                    ("CURRENCY_MATCH", item.currency_matches),
                ) if matched
            ) or ("WEAK_SIGNALS",)
            ranked.append(AIInferenceSuggestion(
                candidate_reference=item.candidate_reference,
                confidence=confidence,
                reason_codes=reasons,
                explanation="Deterministic score derived from normalized matching signals.",
            ))
        ranked.sort(key=lambda item: (-item.confidence, item.candidate_reference))
        return AIInferenceResponse(
            suggestions=tuple(ranked[: self._max_suggestions]),
            model_version=self._model_version,
            prompt_version=request.prompt_version,
        )


def create_ai_inference_provider(
    provider: str, *, model_version: str, max_candidates: int, max_suggestions: int,
    endpoint_url: str | None = None, api_key: str | None = None,
    connect_timeout_seconds: float = 5, read_timeout_seconds: float = 30,
    max_retries: int = 2, retry_backoff_seconds: float = 0.25,
    maximum_response_bytes: int = 262144,
) -> AIInferenceProvider:
    if provider == "disabled":
        return DisabledAIInferenceProvider()
    if provider == "deterministic":
        return DeterministicAIInferenceProvider(
            model_version=model_version,
            max_candidates=max_candidates,
            max_suggestions=max_suggestions,
        )
    if provider == "openai-compatible":
        if not endpoint_url or not api_key:
            raise ValueError("hosted AI inference requires an endpoint and API key")
        from .openai_compatible import OpenAICompatibleInferenceProvider
        return OpenAICompatibleInferenceProvider(
            endpoint_url=endpoint_url, api_key=api_key, model_version=model_version,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds, max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            maximum_response_bytes=maximum_response_bytes,
        )
    raise ValueError("unsupported AI inference provider")
