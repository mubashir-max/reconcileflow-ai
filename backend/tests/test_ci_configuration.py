from pathlib import Path


ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_runs_for_pushes_and_pull_requests_with_minimal_permissions():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in workflow
    assert "pull_request:" in workflow
    assert "contents: read" in workflow


def test_ci_covers_supported_python_and_postgresql():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'python-version: ["3.12", "3.14"]' in workflow
    assert "postgres:17-alpine" in workflow
    assert "alembic upgrade head" in workflow
    assert "RECONCILEFLOW_TEST_POSTGRESQL_URL" in workflow


def test_ci_runs_tests_and_validates_container_image():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pytest" in workflow
    assert "docker compose config --quiet" in workflow
    assert "docker compose build api" in workflow
