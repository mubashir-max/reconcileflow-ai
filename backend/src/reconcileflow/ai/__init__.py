"""Provider-independent foundations for advisory AI-assisted matching."""

from .models import CandidateRecordSet, MatchSuggestionStatus
from .inference import (
    AIInferenceDisabledError,
    AIInferenceError,
    AIInferenceProvider,
    AIInferenceRequest,
    AIInferenceResponse,
    AIInferenceResponseError,
    AIInferenceSuggestion,
    DeterministicAIInferenceProvider,
    DisabledAIInferenceProvider,
    NormalizedMatchFeatures,
    create_ai_inference_provider,
)

__all__ = [
    "AIInferenceDisabledError", "AIInferenceError", "AIInferenceProvider",
    "AIInferenceRequest", "AIInferenceResponse", "AIInferenceResponseError",
    "AIInferenceSuggestion", "CandidateRecordSet", "DeterministicAIInferenceProvider",
    "DisabledAIInferenceProvider", "MatchSuggestionStatus", "NormalizedMatchFeatures",
    "create_ai_inference_provider",
]
