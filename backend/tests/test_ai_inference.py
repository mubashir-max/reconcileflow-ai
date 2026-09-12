import pytest

from reconcileflow.ai import (
    AIInferenceDisabledError,
    AIInferenceError,
    AIInferenceRequest,
    AIInferenceResponseError,
    AIInferenceSuggestion,
    DeterministicAIInferenceProvider,
    DisabledAIInferenceProvider,
    NormalizedMatchFeatures,
    create_ai_inference_provider,
)
from reconcileflow.api.app import create_app
from reconcileflow.api.config import APISettings


def _features(reference: str = "candidate-1") -> NormalizedMatchFeatures:
    return NormalizedMatchFeatures(
        candidate_reference=reference,
        amount_similarity=1.0,
        date_similarity=0.8,
        reference_similarity=0.6,
        currency_matches=True,
    )


@pytest.mark.anyio
async def test_disabled_provider_is_safe_default():
    app = create_app(APISettings(environment="test", _env_file=None))
    assert isinstance(app.state.ai_inference_provider, DisabledAIInferenceProvider)
    request = AIInferenceRequest((_features(),), "prompt-v1")
    with pytest.raises(AIInferenceDisabledError, match="not enabled"):
        await app.state.ai_inference_provider.infer(request)


@pytest.mark.anyio
async def test_deterministic_provider_returns_repeatable_bounded_structured_output():
    provider = DeterministicAIInferenceProvider(
        model_version="local-v1", max_candidates=3, max_suggestions=1
    )
    request = AIInferenceRequest((_features("second"), _features("first")), "prompt-v1")
    first = await provider.infer(request)
    second = await provider.infer(request)
    assert first == second
    assert len(first.suggestions) == 1
    assert first.model_version == "local-v1"
    assert first.prompt_version == "prompt-v1"
    assert 0 <= first.suggestions[0].confidence <= 1


@pytest.mark.anyio
async def test_provider_rejects_oversized_candidate_batch_without_echoing_data():
    provider = DeterministicAIInferenceProvider(
        model_version="local-v1", max_candidates=1, max_suggestions=1
    )
    request = AIInferenceRequest((_features("private-a"), _features("private-b")), "prompt-v1")
    with pytest.raises(AIInferenceError) as error:
        await provider.infer(request)
    assert "private-a" not in str(error.value)
    assert "private-b" not in str(error.value)


@pytest.mark.parametrize("field", ("amount_similarity", "date_similarity", "reference_similarity"))
def test_normalized_features_reject_invalid_scores(field):
    values = dict(
        candidate_reference="candidate", amount_similarity=0.5,
        date_similarity=0.5, reference_similarity=0.5, currency_matches=True,
    )
    values[field] = float("nan")
    with pytest.raises(ValueError, match=field):
        NormalizedMatchFeatures(**values)


def test_structured_response_rejects_malformed_provider_values():
    with pytest.raises(AIInferenceResponseError, match="invalid response"):
        AIInferenceSuggestion("candidate", 1.5, ("VALID",), "explanation")
    with pytest.raises(AIInferenceResponseError, match="invalid response"):
        AIInferenceSuggestion("candidate", 0.5, ("not-valid",), "explanation")


def test_factory_constructs_only_supported_providers():
    provider = create_ai_inference_provider(
        "deterministic", model_version="local-v1", max_candidates=2, max_suggestions=1
    )
    assert isinstance(provider, DeterministicAIInferenceProvider)
    with pytest.raises(ValueError, match="unsupported"):
        create_ai_inference_provider(
            "hosted", model_version="remote", max_candidates=2, max_suggestions=1
        )
