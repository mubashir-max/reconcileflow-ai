"""Centralized API exceptions and privacy-safe error responses."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


LOGGER = logging.getLogger("reconcileflow.api")


class APIError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def _response(status_code: int, code: str, message: str, details: list[dict] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or []}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def handle_api_error(_request: Request, error: APIError) -> JSONResponse:
        return _response(error.status_code, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        safe_details = [
            {
                "location": [str(item) for item in issue["loc"]],
                "message": issue["msg"],
                "type": issue["type"],
            }
            for issue in error.errors()
        ]
        return _response(422, "REQUEST_VALIDATION_ERROR", "The request is invalid.", safe_details)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        LOGGER.error(
            "unhandled_api_error",
            extra={"error_type": type(error).__name__, "method": request.method, "route": request.url.path},
        )
        return _response(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred.")
