"""Prevent v0.5 release artifacts and storage security guarantees from drifting."""

from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_v05_release_artifacts_describe_the_completed_platform():
    release = (ROOT / "docs" / "releases" / "v0.5.0.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "release-checklists" / "v0.5.0.md").read_text(encoding="utf-8")
    for capability in (
        "Cloud Storage", "S3-compatible", "presigned", "finalization",
        "cleanup", "quotas", "integrity", "tenant",
    ):
        assert capability.lower() in release.lower()
    for requirement in (
        "v0.5.0", "Python 3.12 and 3.14", "PostgreSQL", "MinIO",
        "read-only", "signed URLs", "object keys",
    ):
        assert requirement in checklist


def test_readme_documents_v05_operations_and_security_boundaries():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for value in (
        "## v0.5 capabilities",
        "RECONCILEFLOW_STORAGE_PROVIDER",
        "files/presigned-upload",
        "files/finalize",
        "storage-usage",
        "python -m reconcileflow.maintenance verify-storage",
    ):
        assert value in readme
    lowered = readme.lower()
    assert "never place credentials in the endpoint url" in lowered
    assert "never object keys, paths, signed urls, credentials, or file contents" in lowered
