"""Request-scoped API dependencies."""

from fastapi import Request

from .config import APISettings


def get_settings(request: Request) -> APISettings:
    return request.app.state.settings
