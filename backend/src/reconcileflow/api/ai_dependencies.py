"""FastAPI dependencies for advisory AI inference."""

from typing import Annotated

from fastapi import Depends, Request

from reconcileflow.ai import AIInferenceProvider, ReconciliationCandidateGenerator


def get_ai_inference_provider(request: Request) -> AIInferenceProvider:
    return request.app.state.ai_inference_provider


AIInferenceProviderDependency = Annotated[AIInferenceProvider, Depends(get_ai_inference_provider)]


def get_ai_candidate_generator(request: Request) -> ReconciliationCandidateGenerator:
    return request.app.state.ai_candidate_generator


AIReconciliationCandidateGeneratorDependency = Annotated[
    ReconciliationCandidateGenerator, Depends(get_ai_candidate_generator)
]
