"""Explicit command-line evaluation runner; live providers require opt-in."""

from __future__ import annotations

import argparse
import asyncio
import json

from reconcileflow.api.config import APISettings

from .evaluation import AISuggestionEvaluator, EvaluationCase, EvaluationThresholds
from .inference import AIInferenceRequest, NormalizedMatchFeatures, create_ai_inference_provider


def _synthetic_cases(prompt_version: str) -> tuple[EvaluationCase, ...]:
    strong = NormalizedMatchFeatures("synthetic-strong", 0.98, 0.95, 0.96, True)
    return (
        EvaluationCase(
            request=AIInferenceRequest((strong,), prompt_version),
            expected_candidate_references=frozenset({"synthetic-strong"}),
        ),
    )


async def _run(args) -> int:
    settings = APISettings()
    provider_name = args.provider
    if provider_name == "openai-compatible" and not args.allow_paid_live_provider:
        raise SystemExit("live provider evaluation requires --allow-paid-live-provider")
    provider = create_ai_inference_provider(
        provider_name, model_version=settings.ai_model_version,
        max_candidates=settings.ai_max_candidates_per_request,
        max_suggestions=settings.ai_max_suggestions_per_response,
        endpoint_url=settings.ai_endpoint_url,
        api_key=settings.ai_api_key.get_secret_value() if settings.ai_api_key else None,
        connect_timeout_seconds=settings.ai_connect_timeout_seconds,
        read_timeout_seconds=settings.ai_read_timeout_seconds,
        max_retries=settings.ai_max_retries,
        retry_backoff_seconds=settings.ai_retry_backoff_seconds,
        maximum_response_bytes=settings.ai_maximum_response_bytes,
    )
    evaluator = AISuggestionEvaluator(
        provider=provider, provider_name=provider_name,
        inference_config_version=settings.ai_inference_config_version,
        thresholds=EvaluationThresholds(
            minimum_precision=settings.ai_evaluation_min_precision,
            minimum_recall=settings.ai_evaluation_min_recall,
            minimum_coverage=settings.ai_evaluation_min_coverage,
            maximum_brier_score=settings.ai_evaluation_maximum_brier_score,
        ),
    )
    report = await evaluator.evaluate(_synthetic_cases(settings.ai_prompt_version))
    print(json.dumps(report.as_safe_dict(), sort_keys=True))
    return 0 if report.passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m reconcileflow.ai.evaluate")
    parser.add_argument(
        "--provider", choices=("deterministic", "openai-compatible"), default="deterministic"
    )
    parser.add_argument("--allow-paid-live-provider", action="store_true")
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
