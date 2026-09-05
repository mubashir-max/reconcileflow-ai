import pytest
from pydantic import ValidationError

from reconcileflow.api.config import APISettings, Environment


def test_settings_have_safe_development_defaults():
    settings = APISettings(_env_file=None)
    assert settings.app_name == "ReconcileFlow AI"
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.api_prefix == "/api/v1"
    assert settings.debug is False


def test_settings_load_prefixed_environment_variables(monkeypatch):
    monkeypatch.setenv("RECONCILEFLOW_APP_NAME", "Configured ReconcileFlow")
    monkeypatch.setenv("RECONCILEFLOW_ENVIRONMENT", "test")
    monkeypatch.setenv("RECONCILEFLOW_DEBUG", "true")
    monkeypatch.setenv("RECONCILEFLOW_API_PREFIX", "/api/test")
    settings = APISettings(_env_file=None)
    assert settings.app_name == "Configured ReconcileFlow"
    assert settings.environment is Environment.TEST
    assert settings.debug is True
    assert settings.api_prefix == "/api/test"


@pytest.mark.parametrize("prefix", ["api/v1", "/", "/api/v1/"])
def test_invalid_api_prefix_is_rejected(prefix):
    with pytest.raises(ValidationError, match="api_prefix"):
        APISettings(api_prefix=prefix, _env_file=None)


def test_settings_are_immutable():
    settings = APISettings(_env_file=None)
    with pytest.raises(ValidationError):
        settings.debug = True
