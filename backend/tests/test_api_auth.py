from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import Base, OrganizationMembershipRecord, OrganizationRecord, UserRecord


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def auth_app(tmp_path):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'auth.db').as_posix()}"
    app = create_app(APISettings(environment="test", database_url=database_url, _env_file=None))
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


def _registration(**overrides):
    return {
        "email": " Owner@Example.COM ",
        "password": "correct horse battery staple",
        "display_name": "Account Owner",
        "organization_name": "Acme Finance",
        **overrides,
    }


@pytest.mark.anyio
async def test_registration_creates_user_organization_and_owner_membership(auth_app):
    async with AsyncClient(transport=ASGITransport(app=auth_app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post("/api/v1/auth/register", json=_registration())

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "owner@example.com"
    assert body["membership"]["role"] == "OWNER"
    assert body["membership"]["organization"]["slug"] == "acme-finance"
    assert "password" not in response.text.lower()

    with auth_app.state.database.session() as session:
        user = session.scalar(select(UserRecord))
        assert user.password_hash.startswith("$argon2")
        assert user.password_hash != _registration()["password"]
        assert session.scalar(select(func.count()).select_from(OrganizationRecord)) == 1
        assert session.scalar(select(func.count()).select_from(OrganizationMembershipRecord)) == 1


@pytest.mark.anyio
async def test_login_accepts_normalized_email_and_correct_password(auth_app):
    async with AsyncClient(transport=ASGITransport(app=auth_app, raise_app_exceptions=False), base_url="http://test") as client:
        await client.post("/api/v1/auth/register", json=_registration())
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "OWNER@example.com", "password": "correct horse battery staple"},
        )

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["memberships"][0]["role"] == "OWNER"
    assert "password" not in response.text.lower()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "login",
    [
        {"email": "owner@example.com", "password": "incorrect password"},
        {"email": "unknown@example.com", "password": "incorrect password"},
    ],
)
async def test_login_returns_same_safe_error_for_bad_credentials(auth_app, login):
    async with AsyncClient(transport=ASGITransport(app=auth_app, raise_app_exceptions=False), base_url="http://test") as client:
        await client.post("/api/v1/auth/register", json=_registration())
        response = await client.post("/api/v1/auth/login", json=login)

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "INVALID_CREDENTIALS",
            "message": "The email or password is incorrect.",
            "details": [],
        }
    }


@pytest.mark.anyio
async def test_duplicate_registration_is_rejected_without_partial_data(auth_app):
    async with AsyncClient(transport=ASGITransport(app=auth_app, raise_app_exceptions=False), base_url="http://test") as client:
        first = await client.post("/api/v1/auth/register", json=_registration())
        duplicate = await client.post(
            "/api/v1/auth/register",
            json=_registration(email="owner@example.com", organization_name="Other Organization"),
        )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"
    with auth_app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(UserRecord)) == 1
        assert session.scalar(select(func.count()).select_from(OrganizationRecord)) == 1


@pytest.mark.anyio
async def test_disabled_user_cannot_login(auth_app):
    async with AsyncClient(transport=ASGITransport(app=auth_app, raise_app_exceptions=False), base_url="http://test") as client:
        await client.post("/api/v1/auth/register", json=_registration())
        with auth_app.state.database.session() as session:
            user = session.scalar(select(UserRecord))
            user.is_active = False
            session.commit()
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "correct horse battery staple"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.anyio
@pytest.mark.parametrize("password", ["short", "            ", "x" * 129])
async def test_weak_or_oversized_password_is_rejected(auth_app, password):
    async with AsyncClient(transport=ASGITransport(app=auth_app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post("/api/v1/auth/register", json=_registration(password=password))

    assert response.status_code == 422
    with auth_app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(UserRecord)) == 0


@pytest.mark.anyio
async def test_openapi_documents_authentication_without_password_hash(auth_app):
    async with AsyncClient(transport=ASGITransport(app=auth_app), base_url="http://test") as client:
        document = (await client.get("/openapi.json")).json()

    assert "/api/v1/auth/register" in document["paths"]
    assert "/api/v1/auth/login" in document["paths"]
    assert "password_hash" not in str(document)
