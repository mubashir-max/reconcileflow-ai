"""Prevent v0.3 release documentation and security defaults from drifting."""

from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_v03_release_artifacts_exist_and_describe_completed_platform():
    release = (ROOT / "docs" / "releases" / "v0.3.0.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "release-checklists" / "v0.3.0.md").read_text(encoding="utf-8")
    for capability in ("Authentication", "Multi-Tenancy", "Argon2", "refresh-token", "lockout", "security"):
        assert capability.lower() in release.lower()
    assert "v0.3.0" in checklist
    assert "Python 3.12 and 3.14" in checklist
    assert "PostgreSQL" in checklist
    assert "Docker" in checklist


def test_readme_documents_authentication_tenancy_and_configuration():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for value in (
        "## v0.3 capabilities",
        "POST /api/v1/auth/register",
        "X-Organization-ID",
        "RECONCILEFLOW_LOGIN_MAX_FAILED_ATTEMPTS",
        "RECONCILEFLOW_LOGIN_LOCKOUT_MINUTES",
        "OWNER",
        "ADMIN",
        "ANALYST",
        "VIEWER",
    ):
        assert value in readme
    assert "Authentication, authorization, or tenant isolation" not in readme
