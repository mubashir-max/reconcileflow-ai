"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from reconcileflow.persistence.database import Database

from .config import APISettings
from .errors import register_exception_handlers
from .routes import api_router
from .schemas import ServiceInfoResponse


def create_app(settings: APISettings | None = None) -> FastAPI:
    """Build an isolated application instance with validated settings."""
    resolved = settings or APISettings()
    database = Database(resolved)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        database.dispose()

    app = FastAPI(
        title=resolved.app_name,
        version=resolved.app_version,
        description="Versioned API for ReconcileFlow financial reconciliation.",
        debug=resolved.debug,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.database = database
    register_exception_handlers(app)
    app.include_router(api_router, prefix=resolved.api_prefix)

    @app.get("/", response_model=ServiceInfoResponse, tags=["service"], summary="Get service information")
    def service_information() -> ServiceInfoResponse:
        return ServiceInfoResponse(
            name=resolved.app_name,
            version=resolved.app_version,
            environment=resolved.environment,
            api_prefix=resolved.api_prefix,
            documentation_url=app.docs_url or "/docs",
        )

    return app


app = create_app()
