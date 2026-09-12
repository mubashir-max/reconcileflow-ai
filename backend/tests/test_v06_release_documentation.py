"""Prevent v0.6 release artifacts and AI safety guarantees from drifting."""
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_v06_release_artifacts_describe_the_completed_platform():
    release = (ROOT / "docs" / "releases" / "v0.6.0.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "release-checklists" / "v0.6.0.md").read_text(encoding="utf-8")
    for capability in (
        "AI-Assisted Matching", "provider-independent", "deterministic",
        "OpenAI-compatible", "quality evaluation", "request limits",
        "token limits", "observability", "tenant",
    ):
        assert capability.lower() in release.lower()
    for requirement in (
        "v0.6.0", "Python 3.12 and 3.14", "PostgreSQL", "disabled by default",
        "credentials", "raw responses", "candidate identifiers",
    ):
        assert requirement in checklist


def test_readme_documents_v06_ai_boundaries():
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    for value in (
        "## v0.6 capabilities", "disabled-by-default", "deterministic local inference",
        "privacy-minimized", "usage limits", "operational inspection",
    ):
        assert value.lower() in readme
