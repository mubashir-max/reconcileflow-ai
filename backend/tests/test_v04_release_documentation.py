"""Prevent v0.4 release artifacts and operational guarantees from drifting."""

from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_v04_release_artifacts_describe_the_completed_platform():
    release = (ROOT / "docs" / "releases" / "v0.4.0.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "release-checklists" / "v0.4.0.md").read_text(
        encoding="utf-8"
    )
    for capability in (
        "Background Processing", "asynchronous", "heartbeats", "retry",
        "cancellation", "deadlines", "priorities", "retention", "lifecycle",
    ):
        assert capability.lower() in release.lower()
    for requirement in (
        "v0.4.0", "Python 3.12 and 3.14", "PostgreSQL", "Docker Compose",
        "tenant-isolated", "infrastructure identifiers",
    ):
        assert requirement in checklist


def test_readme_documents_v04_operations_and_security_boundaries():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for value in (
        "## v0.4 capabilities",
        "python -m reconcileflow.worker",
        "GET /api/v1/background-jobs/{job_id}/events",
        "RECONCILEFLOW_DEFAULT_JOB_TIMEOUT_SECONDS",
        "RECONCILEFLOW_JOB_PRIORITY_AGING_SECONDS",
        "python -m reconcileflow.maintenance cleanup",
    ):
        assert value in readme
    assert (
        "worker names, hostnames, process ids, and connection details remain internal"
        in readme.lower()
    )
