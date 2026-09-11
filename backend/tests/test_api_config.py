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


def test_database_settings_load_without_exposing_password(monkeypatch):
    url = "postgresql+psycopg://api_user:top-secret@localhost:5432/reconcileflow"
    monkeypatch.setenv("RECONCILEFLOW_DATABASE_URL", url)
    settings = APISettings(_env_file=None)
    assert settings.database_url.get_secret_value() == url
    assert "top-secret" not in repr(settings)


def test_invalid_database_scheme_is_rejected():
    with pytest.raises(ValidationError, match="database_url"):
        APISettings(database_url="mysql://user:password@localhost/database", _env_file=None)


def test_upload_settings_are_validated(tmp_path):
    settings = APISettings(
        storage_provider="LOCAL", upload_directory=tmp_path / "uploads",
        max_upload_size_bytes=2048, _env_file=None,
    )
    assert settings.storage_provider == "local"
    assert settings.upload_directory == tmp_path / "uploads"
    assert settings.max_upload_size_bytes == 2048
    with pytest.raises(ValidationError, match="storage_provider"):
        APISettings(storage_provider="unsupported", _env_file=None)


def test_s3_settings_are_secret_and_restrict_insecure_remote_endpoints():
    settings = APISettings(
        environment="test",
        storage_provider="s3",
        s3_endpoint_url="http://localhost:9000",
        s3_bucket="reconcileflow-uploads",
        s3_access_key_id="local-user",
        s3_secret_access_key="local-secret",
        s3_use_path_style=True,
        s3_auto_create_bucket=True,
        _env_file=None,
    )
    assert settings.s3_access_key_id.get_secret_value() == "local-user"
    assert settings.s3_secret_access_key.get_secret_value() == "local-secret"
    assert "local-secret" not in repr(settings)
    assert settings.presigned_url_ttl_seconds == 300
    with pytest.raises(ValidationError):
        APISettings(presigned_url_ttl_seconds=30, _env_file=None)
    with pytest.raises(ValidationError, match="configured together"):
        APISettings(s3_access_key_id="only-one", _env_file=None)
    with pytest.raises(ValidationError, match="plain HTTP"):
        APISettings(
            storage_provider="s3", s3_endpoint_url="http://objects.example.com",
            s3_bucket="private-bucket", _env_file=None,
        )
    with pytest.raises(ValidationError, match="must not contain credentials"):
        APISettings(
            storage_provider="s3", s3_endpoint_url="https://user:pass@example.com",
            s3_bucket="private-bucket", _env_file=None,
        )
    with pytest.raises(ValidationError, match="provisioned explicitly"):
        APISettings(
            environment="production", storage_provider="s3",
            s3_bucket="private-bucket", s3_auto_create_bucket=True,
            token_signing_secret="p" * 32, _env_file=None,
        )


def test_token_settings_are_secret_and_validated():
    settings = APISettings(token_signing_secret="a" * 32, access_token_ttl_minutes=10, refresh_token_ttl_days=7, _env_file=None)
    assert settings.token_signing_secret.get_secret_value() == "a" * 32
    assert "a" * 32 not in repr(settings)
    assert settings.access_token_ttl_minutes == 10
    assert settings.refresh_token_ttl_days == 7


def test_login_protection_settings_are_validated():
    settings = APISettings(login_max_failed_attempts=3, login_lockout_minutes=10, _env_file=None)
    assert settings.login_max_failed_attempts == 3
    assert settings.login_lockout_minutes == 10
    with pytest.raises(ValidationError):
        APISettings(login_max_failed_attempts=1, _env_file=None)
    with pytest.raises(ValidationError):
        APISettings(login_lockout_minutes=0, _env_file=None)


def test_worker_settings_are_validated():
    settings = APISettings(
        worker_id="worker-a",
        worker_poll_interval_seconds=0.5,
        worker_stale_timeout_seconds=60,
        worker_retry_delay_seconds=5,
        max_manual_job_retries=4,
        worker_health_stale_seconds=90,
        default_job_timeout_seconds=120,
        maximum_job_timeout_seconds=600,
        job_priority_aging_seconds=120,
        _env_file=None,
    )
    assert settings.worker_id == "worker-a"
    assert settings.worker_poll_interval_seconds == 0.5
    assert settings.worker_stale_timeout_seconds == 60
    assert settings.worker_retry_delay_seconds == 5
    assert settings.max_manual_job_retries == 4
    assert settings.worker_health_stale_seconds == 90
    assert settings.default_job_timeout_seconds == 120
    assert settings.maximum_job_timeout_seconds == 600
    assert settings.job_priority_aging_seconds == 120
    with pytest.raises(ValidationError):
        APISettings(worker_id=" ", _env_file=None)
    with pytest.raises(ValidationError):
        APISettings(worker_poll_interval_seconds=0, _env_file=None)
    with pytest.raises(ValidationError):
        APISettings(max_manual_job_retries=0, _env_file=None)
    with pytest.raises(ValidationError):
        APISettings(worker_health_stale_seconds=10, _env_file=None)
    with pytest.raises(ValidationError):
        APISettings(
            default_job_timeout_seconds=601,
            maximum_job_timeout_seconds=600,
            _env_file=None,
        )
    with pytest.raises(ValidationError):
        APISettings(job_priority_aging_seconds=29, _env_file=None)


def test_short_token_secret_is_rejected():
    with pytest.raises(ValidationError, match="token_signing_secret"):
        APISettings(token_signing_secret="too-short", _env_file=None)


def test_blank_token_secret_is_rejected():
    with pytest.raises(ValidationError, match="token_signing_secret"):
        APISettings(token_signing_secret=" " * 32, _env_file=None)


def test_production_rejects_development_token_secret():
    with pytest.raises(ValidationError, match="production requires"):
        APISettings(environment="production", _env_file=None)
