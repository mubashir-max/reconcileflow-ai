"""Provider-independent, privacy-safe evaluation of advisory AI suggestions."""

from __future__ import annotations

from dataclasses import dataclass

from .inference import AIInferenceError, AIInferenceProvider, AIInferenceRequest


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    request: AIInferenceRequest
    expected_candidate_references: frozenset[str]

    def __post_init__(self) -> None:
        submitted = {item.candidate_reference for item in self.request.features}
        if not self.expected_candidate_references <= submitted:
            raise ValueError("expected candidates must be present in the evaluation request")


@dataclass(frozen=True, slots=True)
class EvaluationThresholds:
    minimum_precision: float = 0.8
    minimum_recall: float = 0.8
    minimum_coverage: float = 0.8
    maximum_brier_score: float = 0.25

    def __post_init__(self) -> None:
        for name in (
            "minimum_precision", "minimum_recall", "minimum_coverage",
            "maximum_brier_score",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    case_count: int
    expected_count: int
    suggestion_count: int
    true_positive_count: int
    false_positive_count: int
    false_negative_count: int
    provider_error_count: int
    safety_violation_count: int
    precision: float
    recall: float
    coverage: float
    brier_score: float
    provider: str
    model_version: str
    prompt_version: str
    inference_config_version: str
    passed: bool

    def as_safe_dict(self) -> dict[str, int | float | str | bool]:
        """Return aggregate metrics only; candidate identifiers are intentionally absent."""
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


class AISuggestionEvaluator:
    def __init__(
        self, *, provider: AIInferenceProvider, provider_name: str,
        inference_config_version: str, thresholds: EvaluationThresholds,
    ) -> None:
        self._provider = provider
        self._provider_name = _safe_version(provider_name, "provider_name")
        self._inference_config_version = _safe_version(
            inference_config_version, "inference_config_version"
        )
        self._thresholds = thresholds

    async def evaluate(self, cases: tuple[EvaluationCase, ...]) -> EvaluationReport:
        if not cases:
            raise ValueError("at least one evaluation case is required")
        true_positives = false_positives = false_negatives = 0
        errors = safety_violations = covered_cases = 0
        squared_error = 0.0
        scored_candidates = 0
        model_versions: set[str] = set()
        prompt_versions: set[str] = set()

        for case in cases:
            submitted = {item.candidate_reference for item in case.request.features}
            try:
                response = await self._provider.infer(case.request)
            except AIInferenceError:
                errors += 1
                false_negatives += len(case.expected_candidate_references)
                continue
            model_versions.add(response.model_version)
            prompt_versions.add(response.prompt_version)
            predicted = {item.candidate_reference for item in response.suggestions}
            unknown = predicted - submitted
            safety_violations += len(unknown)
            predicted &= submitted
            if predicted:
                covered_cases += 1
            true_positives += len(predicted & case.expected_candidate_references)
            false_positives += len(predicted - case.expected_candidate_references)
            false_negatives += len(case.expected_candidate_references - predicted)
            confidence_by_reference = {
                item.candidate_reference: item.confidence
                for item in response.suggestions if item.candidate_reference in submitted
            }
            for candidate_reference in submitted:
                expected = 1.0 if candidate_reference in case.expected_candidate_references else 0.0
                confidence = confidence_by_reference.get(candidate_reference, 0.0)
                squared_error += (confidence - expected) ** 2
                scored_candidates += 1

        precision = _ratio(true_positives, true_positives + false_positives, empty=1.0)
        recall = _ratio(true_positives, true_positives + false_negatives, empty=1.0)
        coverage = covered_cases / len(cases)
        brier_score = squared_error / scored_candidates if scored_candidates else 1.0
        versions_are_consistent = len(model_versions) <= 1 and len(prompt_versions) <= 1
        if not versions_are_consistent:
            safety_violations += 1
        passed = (
            errors == 0 and safety_violations == 0
            and precision >= self._thresholds.minimum_precision
            and recall >= self._thresholds.minimum_recall
            and coverage >= self._thresholds.minimum_coverage
            and brier_score <= self._thresholds.maximum_brier_score
        )
        return EvaluationReport(
            case_count=len(cases),
            expected_count=true_positives + false_negatives,
            suggestion_count=true_positives + false_positives,
            true_positive_count=true_positives,
            false_positive_count=false_positives,
            false_negative_count=false_negatives,
            provider_error_count=errors,
            safety_violation_count=safety_violations,
            precision=round(precision, 6), recall=round(recall, 6),
            coverage=round(coverage, 6), brier_score=round(brier_score, 6),
            provider=self._provider_name,
            model_version=next(iter(model_versions), "unavailable"),
            prompt_version=next(iter(prompt_versions), cases[0].request.prompt_version),
            inference_config_version=self._inference_config_version,
            passed=passed,
        )


def _ratio(numerator: int, denominator: int, *, empty: float) -> float:
    return numerator / denominator if denominator else empty


def _safe_version(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 100:
        raise ValueError(f"{field} must be nonblank and at most 100 characters")
    return normalized
