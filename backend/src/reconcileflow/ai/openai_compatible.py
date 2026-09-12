"""Secure OpenAI-compatible Responses API inference provider."""

from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from .inference import (
    AIInferenceError,
    AIInferenceRequest,
    AIInferenceResponse,
    AIInferenceResponseError,
    AIInferenceSuggestion,
)


_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["suggestions"],
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["candidate_reference", "confidence", "reason_codes", "explanation"],
                "properties": {
                    "candidate_reference": {"type": "string", "maxLength": 200},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason_codes": {
                        "type": "array", "minItems": 1, "maxItems": 10,
                        "items": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{0,49}$"},
                    },
                    "explanation": {"type": "string", "minLength": 1, "maxLength": 500},
                },
            },
        }
    },
}


class OpenAICompatibleInferenceProvider:
    """Call a compatible Responses endpoint with minimized structured signals only."""

    def __init__(
        self, *, endpoint_url: str, api_key: str, model_version: str,
        connect_timeout_seconds: float, read_timeout_seconds: float,
        max_retries: int, retry_backoff_seconds: float, maximum_response_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        parsed_endpoint = urlsplit(endpoint_url)
        local_http = (
            parsed_endpoint.scheme == "http"
            and parsed_endpoint.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        if (
            (parsed_endpoint.scheme != "https" and not local_http) or not parsed_endpoint.hostname
            or parsed_endpoint.username or parsed_endpoint.password
            or parsed_endpoint.query or parsed_endpoint.fragment
        ):
            raise ValueError("hosted inference endpoint must be an HTTPS URL without credentials")
        if not api_key.strip():
            raise ValueError("hosted inference API key must not be blank")
        if not model_version.strip() or len(model_version) > 100:
            raise ValueError("model_version must be nonblank and at most 100 characters")
        if not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be between 0 and 5")
        if not 1024 <= maximum_response_bytes <= 1048576:
            raise ValueError("maximum_response_bytes must be between 1024 and 1048576")
        self._endpoint_url = endpoint_url
        self._api_key = api_key.strip()
        self._model_version = model_version.strip()
        self._timeout = httpx.Timeout(
            read_timeout_seconds, connect=connect_timeout_seconds,
            write=connect_timeout_seconds, pool=connect_timeout_seconds,
        )
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._maximum_response_bytes = maximum_response_bytes
        self._transport = transport
        self._sleep = sleep

    async def infer(self, request: AIInferenceRequest) -> AIInferenceResponse:
        payload = self._payload(request)
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            for attempt in range(self._max_retries + 1):
                try:
                    response = await client.post(self._endpoint_url, headers=headers, json=payload)
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt < self._max_retries:
                        await self._sleep(self._retry_backoff_seconds * (2 ** attempt))
                        continue
                    raise AIInferenceError("AI inference provider is temporarily unavailable") from None
                if response.status_code == 429 or 500 <= response.status_code <= 599:
                    if attempt < self._max_retries:
                        await self._sleep(self._retry_backoff_seconds * (2 ** attempt))
                        continue
                    raise AIInferenceError("AI inference provider is temporarily unavailable")
                if response.status_code in {401, 403}:
                    raise AIInferenceError("AI inference provider authentication failed")
                if response.status_code >= 400:
                    raise AIInferenceError("AI inference provider rejected the request")
                if len(response.content) > self._maximum_response_bytes:
                    raise AIInferenceResponseError("inference provider returned an invalid response")
                return self._parse_response(response, request)
        raise AIInferenceError("AI inference provider is temporarily unavailable")

    def _payload(self, request: AIInferenceRequest) -> dict:
        candidates = [
            {
                "candidate_reference": item.candidate_reference,
                "amount_similarity": item.amount_similarity,
                "date_similarity": item.date_similarity,
                "reference_similarity": item.reference_similarity,
                "currency_matches": item.currency_matches,
            }
            for item in request.features
        ]
        schema = json.loads(json.dumps(_OUTPUT_SCHEMA))
        schema["properties"]["suggestions"]["maxItems"] = len(candidates)
        return {
            "model": self._model_version,
            "instructions": (
                "Rank only the supplied opaque candidates using their normalized signals. "
                "Do not invent candidates or request source financial data."
            ),
            "input": json.dumps({"prompt_version": request.prompt_version, "candidates": candidates}),
            "text": {"format": {
                "type": "json_schema", "name": "reconcileflow_match_suggestions",
                "strict": True, "schema": schema,
            }},
        }

    def _parse_response(self, response: httpx.Response, request: AIInferenceRequest) -> AIInferenceResponse:
        try:
            envelope = response.json()
            output_text = next(
                content["text"]
                for item in envelope["output"] if item.get("type") == "message"
                for content in item["content"] if content.get("type") == "output_text"
            )
            structured = json.loads(output_text)
            suggestions = tuple(AIInferenceSuggestion(
                candidate_reference=item["candidate_reference"],
                confidence=item["confidence"],
                reason_codes=tuple(item["reason_codes"]),
                explanation=item["explanation"],
            ) for item in structured["suggestions"])
        except (KeyError, TypeError, ValueError, StopIteration, json.JSONDecodeError):
            raise AIInferenceResponseError("inference provider returned an invalid response") from None
        if len(suggestions) > len(request.features):
            raise AIInferenceResponseError("inference provider returned an invalid response")
        return AIInferenceResponse(
            suggestions=suggestions,
            model_version=self._model_version,
            prompt_version=request.prompt_version,
        )
