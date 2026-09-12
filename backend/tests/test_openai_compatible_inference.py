import json

import httpx
import pytest

from reconcileflow.ai import (
    AIInferenceError,
    AIInferenceRequest,
    AIInferenceResponseError,
    NormalizedMatchFeatures,
    OpenAICompatibleInferenceProvider,
)


def _request():
    return AIInferenceRequest(features=(NormalizedMatchFeatures(
        candidate_reference="candidate-opaque",
        amount_similarity=0.95,
        date_similarity=0.8,
        reference_similarity=0.75,
        currency_matches=True,
    ),), prompt_version="prompt-v1")


def _success():
    content = json.dumps({"suggestions": [{
        "candidate_reference": "candidate-opaque", "confidence": 0.91,
        "reason_codes": ["AMOUNT_SIMILAR"], "explanation": "Normalized signals agree.",
    }]})
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": content}]}]}


def _provider(handler, *, retries=0, key="super-secret-api-key", sleep=None):
    async def no_sleep(_delay):
        return None
    return OpenAICompatibleInferenceProvider(
        endpoint_url="https://api.example.com/v1/responses",
        api_key=key, model_version="hosted-model-v1",
        connect_timeout_seconds=1, read_timeout_seconds=2,
        max_retries=retries, retry_backoff_seconds=0,
        maximum_response_bytes=4096,
        transport=httpx.MockTransport(handler), sleep=sleep or no_sleep,
    )


@pytest.mark.anyio
async def test_provider_sends_only_minimized_signals_and_structured_schema():
    captured = {}
    def handler(request: httpx.Request):
        captured["request"] = request
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_success())
    response = await _provider(handler).infer(_request())
    sent = json.dumps(captured["payload"])
    assert captured["request"].headers["authorization"] == "Bearer super-secret-api-key"
    assert "super-secret-api-key" not in str(captured["request"].url)
    assert "candidate-opaque" in sent
    for forbidden in ("account", "description", "customer", "source_row", "amount_due"):
        assert forbidden not in sent.lower()
    assert captured["payload"]["text"]["format"]["strict"] is True
    assert response.suggestions[0].confidence == 0.91


@pytest.mark.anyio
async def test_temporary_failures_are_retried_with_a_bound():
    calls = 0
    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(429 if calls < 3 else 200, json=_success())
    response = await _provider(handler, retries=2).infer(_request())
    assert calls == 3
    assert len(response.suggestions) == 1


@pytest.mark.anyio
async def test_authentication_failure_is_not_retried_or_leaked():
    calls = 0
    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "provider detail"})
    with pytest.raises(AIInferenceError) as error:
        await _provider(handler, retries=2).infer(_request())
    assert calls == 1
    assert "super-secret" not in str(error.value)
    assert "provider detail" not in str(error.value)


@pytest.mark.anyio
async def test_malformed_and_oversized_responses_are_rejected_safely():
    def malformed(_request):
        return httpx.Response(200, json={"unexpected": "raw-private-output"})
    with pytest.raises(AIInferenceResponseError) as error:
        await _provider(malformed).infer(_request())
    assert "raw-private-output" not in str(error.value)

    def oversized(_request):
        return httpx.Response(200, content=b"x" * 5000)
    with pytest.raises(AIInferenceResponseError, match="invalid response"):
        await _provider(oversized).infer(_request())


@pytest.mark.anyio
async def test_unknown_candidate_is_left_for_workflow_validation():
    body = _success()
    body["output"][0]["content"][0]["text"] = json.dumps({"suggestions": [{
        "candidate_reference": "invented", "confidence": 0.9,
        "reason_codes": ["AMOUNT_SIMILAR"], "explanation": "Signals agree.",
    }]})
    def handler(_request):
        return httpx.Response(200, json=body)
    response = await _provider(handler).infer(_request())
    assert response.suggestions[0].candidate_reference == "invented"


@pytest.mark.parametrize("endpoint", (
    "http://api.example.com/v1/responses",
    "https://user:pass@api.example.com/v1/responses",
    "https://api.example.com/v1/responses?secret=value",
))
def test_provider_constructor_rejects_unsafe_endpoints(endpoint):
    with pytest.raises(ValueError, match="HTTPS URL without credentials"):
        OpenAICompatibleInferenceProvider(
            endpoint_url=endpoint, api_key="secret", model_version="model-v1",
            connect_timeout_seconds=1, read_timeout_seconds=1,
            max_retries=0, retry_backoff_seconds=0, maximum_response_bytes=4096,
        )
