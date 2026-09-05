from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy.exc import OperationalError

from reconcileflow.api import APISettings, Environment, create_app
from reconcileflow.persistence import get_database


def _app(**values):
    settings = APISettings(environment=Environment.TEST, app_version="0.2-test", _env_file=None, **values)
    return create_app(settings)


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _get(app, path):
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        return await client.get(path)


def test_application_factory_creates_isolated_apps():
    first = create_app(APISettings(app_name="First", _env_file=None))
    second = create_app(APISettings(app_name="Second", _env_file=None))
    assert first is not second
    assert first.title == "First"
    assert second.title == "Second"


@pytest.mark.anyio
async def test_root_returns_typed_service_information():
    response = await _get(_app(), "/")
    assert response.status_code == 200
    assert response.json() == {
        "name": "ReconcileFlow AI",
        "version": "0.2-test",
        "environment": "test",
        "api_prefix": "/api/v1",
        "documentation_url": "/docs",
    }


@pytest.mark.anyio
async def test_liveness_endpoint():
    response = await _get(_app(), "/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_readiness_endpoint_uses_validated_settings():
    response = await _get(_app(app_name="Test Service"), "/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "Test Service",
        "version": "0.2-test",
        "environment": "test",
    }


@pytest.mark.anyio
async def test_readiness_returns_safe_503_when_database_is_unavailable():
    app = _app()

    class UnavailableDatabase:
        def check_connection(self):
            raise OperationalError("SELECT 1", {}, RuntimeError("password=secret"))

    app.dependency_overrides[get_database] = lambda: UnavailableDatabase()
    response = await _get(app, "/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "DATABASE_UNAVAILABLE",
            "message": "The service is not ready.",
            "details": [],
        }
    }
    assert "secret" not in response.text
    assert (await _get(app, "/api/v1/health/live")).status_code == 200


@pytest.mark.anyio
async def test_application_shutdown_disposes_initialized_engine():
    app = _app()
    database = app.state.database
    _ = database.engine
    assert database.is_initialized is True
    async with app.router.lifespan_context(app):
        pass
    assert database.is_initialized is False


@pytest.mark.anyio
async def test_routes_use_configured_api_prefix():
    settings = APISettings(api_prefix="/custom/v1", environment="test", _env_file=None)
    app = create_app(settings)
    assert (await _get(app, "/custom/v1/health/live")).status_code == 200
    assert (await _get(app, "/api/v1/health/live")).status_code == 404


@pytest.mark.anyio
async def test_unexpected_errors_return_safe_stable_response():
    app = create_app(APISettings(environment="test", debug=False, _env_file=None))
    router = APIRouter()

    @router.get("/explode")
    def explode():
        raise RuntimeError(r"secret at C:\private\customer.csv")

    app.include_router(router)
    response = await _get(app, "/explode")
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred.",
            "details": [],
        }
    }
    assert "secret" not in response.text
    assert "customer.csv" not in response.text
