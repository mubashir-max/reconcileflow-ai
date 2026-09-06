from importlib.metadata import version

import pytest
from httpx import ASGITransport, AsyncClient

from reconcileflow.api import APISettings, create_app


EXPECTED_VERSION = "0.2.0"


def test_installed_package_reports_v020():
    assert version("reconcileflow-ai") == EXPECTED_VERSION


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_fastapi_and_openapi_report_v020():
    app = create_app(APISettings(environment="test", _env_file=None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        service = await client.get("/")
        openapi = await client.get("/openapi.json")
    assert service.status_code == 200
    assert service.json()["version"] == EXPECTED_VERSION
    assert app.version == EXPECTED_VERSION
    assert openapi.status_code == 200
    assert openapi.json()["info"]["version"] == EXPECTED_VERSION
