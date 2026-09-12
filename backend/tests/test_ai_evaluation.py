from __future__ import annotations

import pytest
from types import SimpleNamespace

from reconcileflow.ai import (
    AIInferenceError,
    AIInferenceRequest,
    AIInferenceResponse,
    AIInferenceSuggestion,
    AISuggestionEvaluator,
    EvaluationCase,
    EvaluationThresholds,
    NormalizedMatchFeatures,
)


def _case(expected=frozenset({"candidate-a"})):
    return EvaluationCase(
        request=AIInferenceRequest(features=(
            NormalizedMatchFeatures("candidate-a", 0.95, 0.9, 0.9, True),
            NormalizedMatchFeatures("candidate-b", 0.4, 0.3, 0.2, True),
        ), prompt_version="prompt-v1"),
        expected_candidate_references=expected,
    )


class StaticProvider:
    def __init__(self, suggestions):
        self.suggestions = suggestions

    async def infer(self, request):
        return AIInferenceResponse(
            suggestions=self.suggestions,
            model_version="model-v1",
            prompt_version=request.prompt_version,
        )


def _suggestion(reference, confidence):
    return AIInferenceSuggestion(
        candidate_reference=reference, confidence=confidence,
        reason_codes=("NORMALIZED_MATCH",), explanation="Normalized signals support this candidate.",
    )


@pytest.mark.anyio
async def test_evaluator_reports_aggregate_quality_and_passes_thresholds():
    evaluator = AISuggestionEvaluator(
        provider=StaticProvider((_suggestion("candidate-a", 0.95),)),
        provider_name="test-provider", inference_config_version="config-v1",
        thresholds=EvaluationThresholds(),
    )
    report = await evaluator.evaluate((_case(),))
    assert report.passed is True
    assert report.precision == report.recall == report.coverage == 1.0
    assert report.brier_score < 0.01
    safe = report.as_safe_dict()
    assert "candidate-a" not in str(safe)
    assert set(safe) == {
        "case_count", "expected_count", "suggestion_count", "true_positive_count",
        "false_positive_count", "false_negative_count", "provider_error_count",
        "safety_violation_count", "precision", "recall", "coverage", "brier_score",
        "provider", "model_version", "prompt_version", "inference_config_version", "passed",
    }


@pytest.mark.anyio
async def test_unknown_candidate_is_a_failing_safety_violation():
    evaluator = AISuggestionEvaluator(
        provider=StaticProvider((_suggestion("invented-candidate", 0.99),)),
        provider_name="test-provider", inference_config_version="config-v1",
        thresholds=EvaluationThresholds(minimum_coverage=0),
    )
    report = await evaluator.evaluate((_case(),))
    assert report.safety_violation_count == 1
    assert report.passed is False


class FailedProvider:
    async def infer(self, request):
        del request
        raise AIInferenceError("safe provider failure")


@pytest.mark.anyio
async def test_provider_failures_are_counted_without_case_data():
    report = await AISuggestionEvaluator(
        provider=FailedProvider(), provider_name="failed-provider",
        inference_config_version="config-v1", thresholds=EvaluationThresholds(),
    ).evaluate((_case(),))
    assert report.provider_error_count == 1
    assert report.passed is False
    assert "candidate" not in str(report.as_safe_dict())


@pytest.mark.anyio
async def test_quality_threshold_failure_is_reported():
    report = await AISuggestionEvaluator(
        provider=StaticProvider((_suggestion("candidate-b", 0.9),)),
        provider_name="test-provider", inference_config_version="config-v1",
        thresholds=EvaluationThresholds(),
    ).evaluate((_case(),))
    assert report.false_positive_count == 1
    assert report.false_negative_count == 1
    assert report.passed is False


def test_evaluation_cases_and_thresholds_are_validated():
    with pytest.raises(ValueError, match="present"):
        _case(frozenset({"not-submitted"}))
    with pytest.raises(ValueError, match="between 0 and 1"):
        EvaluationThresholds(minimum_precision=1.1)


@pytest.mark.anyio
async def test_live_provider_requires_explicit_paid_opt_in():
    from reconcileflow.ai.evaluate import _run

    with pytest.raises(SystemExit, match="allow-paid-live-provider"):
        await _run(SimpleNamespace(
            provider="openai-compatible", allow_paid_live_provider=False
        ))
