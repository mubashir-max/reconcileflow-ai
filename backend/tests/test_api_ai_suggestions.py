from datetime import UTC, datetime, timedelta
from decimal import Decimal
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from reconcileflow.ai import CandidateRecordSet
from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import Base, PersistenceUnitOfWork


PASSWORD = "correct horse battery staple"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def suggestion_app(tmp_path):
    app = create_app(APISettings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'suggestions.db').as_posix()}",
        upload_directory=tmp_path / "uploads",
        ai_inference_provider="deterministic",
        _env_file=None,
    ))
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


async def _register(client: AsyncClient, name: str):
    email = f"{name}@example.com"
    registered = await client.post("/api/v1/auth/register", json={
        "email": email, "password": PASSWORD, "organization_name": f"{name} org",
    })
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return {
        "email": email,
        "user_id": registered.json()["user"]["id"],
        "organization_id": registered.json()["membership"]["organization"]["id"],
        "token": login.json()["access_token"],
    }


def _headers(identity):
    return {
        "Authorization": f"Bearer {identity['token']}",
        "X-Organization-ID": identity["organization_id"],
    }


def _seed(app, identity):
    organization_id = uuid.UUID(identity["organization_id"])
    with app.state.database.session() as session:
        with PersistenceUnitOfWork(session) as work:
            run = work.runs.create(organization_id=organization_id)
            suggestion = work.ai_match_suggestions.create(
                organization_id=organization_id, run_id=run.id,
                candidates=CandidateRecordSet(
                    bank_record_ids=("bank-1",), erp_invoice_ids=("invoice-1",)
                ),
                confidence_score=Decimal("0.91"),
                explanation={"summary": "Normalized signals agree.", "reason_codes": ["AMOUNT_SIMILAR"]},
                features={"amount_similarity": 1.0, "currency_matches": True},
                provider="deterministic", model_version="local-v1",
                prompt_template_version="prompt-v1", inference_config_version="config-v1",
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
    return str(run.id), str(suggestion.id)


@pytest.mark.anyio
async def test_member_lists_and_gets_only_safe_suggestion_fields(suggestion_app):
    async with AsyncClient(transport=ASGITransport(app=suggestion_app), base_url="http://test") as client:
        owner = await _register(client, "suggestion-owner")
        run_id, suggestion_id = _seed(suggestion_app, owner)
        listing = await client.get(
            f"/api/v1/ai-match-suggestions/runs/{run_id}", headers=_headers(owner)
        )
        detail = await client.get(
            f"/api/v1/ai-match-suggestions/{suggestion_id}", headers=_headers(owner)
        )
    assert listing.status_code == detail.status_code == 200
    assert listing.json()["total"] == 1
    assert detail.json()["confidence_score"] == 0.91
    for forbidden in ("features", "provider", "prompt_template", "inference_config", "raw"):
        assert forbidden not in detail.text.lower()


@pytest.mark.anyio
async def test_operator_accepts_suggestion_once_and_decision_is_audited(suggestion_app):
    async with AsyncClient(transport=ASGITransport(app=suggestion_app), base_url="http://test") as client:
        owner = await _register(client, "decision-owner")
        _, suggestion_id = _seed(suggestion_app, owner)
        accepted = await client.post(
            f"/api/v1/ai-match-suggestions/{suggestion_id}/decision",
            headers=_headers(owner), json={"decision": "ACCEPTED"},
        )
        repeated = await client.post(
            f"/api/v1/ai-match-suggestions/{suggestion_id}/decision",
            headers=_headers(owner), json={"decision": "REJECTED"},
        )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ACCEPTED"
    assert accepted.json()["reviewed_by_user_id"] == owner["user_id"]
    assert repeated.status_code == 409
    with suggestion_app.state.database.session() as session:
        events = PersistenceUnitOfWork(session).security_audit_events.list_for_organization(
            uuid.UUID(owner["organization_id"])
        )
        assert any(event.event_type == "AI_SUGGESTION_ACCEPTED" for event in events)


@pytest.mark.anyio
async def test_cross_tenant_suggestion_is_hidden(suggestion_app):
    async with AsyncClient(transport=ASGITransport(app=suggestion_app), base_url="http://test") as client:
        owner = await _register(client, "tenant-a")
        other = await _register(client, "tenant-b")
        _, suggestion_id = _seed(suggestion_app, owner)
        response = await client.get(
            f"/api/v1/ai-match-suggestions/{suggestion_id}", headers=_headers(other)
        )
    assert response.status_code == 404
    assert suggestion_id not in response.text


@pytest.mark.anyio
async def test_authentication_and_openapi_document_generation_endpoint(suggestion_app):
    async with AsyncClient(transport=ASGITransport(app=suggestion_app), base_url="http://test") as client:
        unauthenticated = await client.get(f"/api/v1/ai-match-suggestions/{uuid.uuid4()}")
        schema = (await client.get("/openapi.json")).json()
    assert unauthenticated.status_code == 401
    operation = schema["paths"]["/api/v1/ai-match-suggestions/runs/{run_id}/generate"]["post"]
    assert "BearerAuth" in str(operation)
    assert "Source records remain server-side" in operation["description"]
