"""Provider-independent foundations for advisory AI-assisted matching."""

from .models import CandidateRecordSet, MatchSuggestionStatus
from .openai_compatible import OpenAICompatibleInferenceProvider
from .candidates import (
    CandidateSourceRecord,
    CandidateSourceType,
    GeneratedCandidate,
    ReconciliationCandidateGenerator,
)
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
    "CandidateSourceRecord", "CandidateSourceType", "GeneratedCandidate",
    "DisabledAIInferenceProvider", "MatchSuggestionStatus", "NormalizedMatchFeatures",
    "ReconciliationCandidateGenerator", "create_ai_inference_provider",
    "OpenAICompatibleInferenceProvider",
]
