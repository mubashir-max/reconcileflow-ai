"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from reconcileflow.persistence.database import Database
from reconcileflow.storage import create_file_storage

from .config import APISettings
from .errors import register_exception_handlers
from .routes import api_router
from .schemas import ServiceInfoResponse


def create_app(settings: APISettings | None = None) -> FastAPI:
    """Build an isolated application instance with validated settings."""
    resolved = settings or APISettings()
    database = Database(resolved)
    file_storage = create_file_storage(
        resolved.storage_provider,
        directory=resolved.upload_directory,
        max_size_bytes=resolved.max_upload_size_bytes,
        s3_bucket=resolved.s3_bucket,
        s3_region=resolved.s3_region,
        s3_endpoint_url=resolved.s3_endpoint_url,
        s3_access_key_id=(
            resolved.s3_access_key_id.get_secret_value()
            if resolved.s3_access_key_id else None
        ),
        s3_secret_access_key=(
            resolved.s3_secret_access_key.get_secret_value()
            if resolved.s3_secret_access_key else None
        ),
        s3_use_path_style=resolved.s3_use_path_style,
        s3_connect_timeout_seconds=resolved.s3_connect_timeout_seconds,
        s3_read_timeout_seconds=resolved.s3_read_timeout_seconds,
        s3_auto_create_bucket=resolved.s3_auto_create_bucket,
    )

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
    app.state.file_storage = file_storage
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
