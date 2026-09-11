from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_compose_defines_database_api_healthchecks_and_volumes():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "postgres:17-alpine" in compose
    assert "pg_isready" in compose
    assert "condition: service_healthy" in compose
    assert "/api/v1/health/ready" in compose
    assert "postgres_data:/var/lib/postgresql/data" in compose
    assert "uploaded_files:/app/var/uploads" in compose
    assert "worker:" in compose
    assert '["python", "-m", "reconcileflow.worker"]' in compose
    assert 'RECONCILEFLOW_RUN_MIGRATIONS: "false"' in compose


def test_container_starts_as_non_root_and_applies_migrations():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "USER reconcileflow" in dockerfile
    assert "sed -i 's/\\r$//'" in dockerfile
    assert "alembic upgrade head" in entrypoint
    assert "set -- uvicorn" in entrypoint
    assert 'exec "$@"' in entrypoint
    assert 'org.opencontainers.image.version="0.4.0"' in dockerfile


def test_local_docker_secrets_file_is_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env.docker" in ignored
    assert (ROOT / ".env.docker.example").is_file()
