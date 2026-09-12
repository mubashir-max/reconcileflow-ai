"""FastAPI dependencies for advisory AI inference."""

from typing import Annotated

from fastapi import Depends, Request

from reconcileflow.ai import AIInferenceProvider


def get_ai_inference_provider(request: Request) -> AIInferenceProvider:
    return request.app.state.ai_inference_provider


AIInferenceProviderDependency = Annotated[AIInferenceProvider, Depends(get_ai_inference_provider)]
