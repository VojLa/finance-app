import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_development_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.log_json is False
    assert settings.docs_enabled is True
    assert settings.internal_auth_issuer == "finance-app-next"
    assert settings.internal_auth_audience == "finance-app-python"
    assert settings.background_jobs_enabled is False
    assert settings.background_job_lease_seconds == 300
    assert settings.portfolio_history_runtime_enabled is False
    assert settings.portfolio_history_worker_id == "portfolio-history-api"
    assert settings.scheduled_snapshot_refresh_runner_enabled is False
    assert settings.scheduled_snapshot_refresh_interval_seconds == 300


def test_test_environment_starts_without_auth_secret() -> None:
    settings = Settings(environment="test", internal_auth_secret=None, _env_file=None)

    assert settings.internal_auth_secret is None


def test_negative_auth_clock_skew_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be non-negative"):
        Settings(internal_auth_clock_skew_seconds=-1, _env_file=None)


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"environment": "staging"})


@pytest.mark.parametrize(
    "overrides",
    [
        {"background_job_poll_seconds": 0},
        {"background_job_lease_seconds": 29},
        {"background_job_heartbeat_seconds": 300},
        {"background_job_shutdown_grace_seconds": 61},
    ],
)
def test_invalid_background_job_timing_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"portfolio_history_worker_id": "x" * 164},
        {"portfolio_history_worker_poll_seconds": 0},
        {"portfolio_history_worker_lease_seconds": 29},
        {"portfolio_history_worker_heartbeat_seconds": 300},
        {"portfolio_history_scheduler_poll_seconds": 301},
        {"portfolio_history_shutdown_grace_seconds": 61},
        {"scheduled_snapshot_refresh_interval_seconds": 29},
        {"scheduled_snapshot_refresh_shutdown_grace_seconds": 61},
    ],
)
def test_invalid_portfolio_history_runtime_configuration_is_rejected(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(overrides)


def test_enabled_portfolio_history_runtime_requires_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(portfolio_history_runtime_enabled=True, _env_file=None)


def test_enabled_scheduled_snapshot_refresh_requires_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(scheduled_snapshot_refresh_runner_enabled=True, _env_file=None)


def test_production_requires_safe_configuration() -> None:
    with pytest.raises(ValidationError, match="Invalid production settings"):
        Settings.model_validate({"environment": "production"})


def test_production_rejects_short_auth_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings.model_validate(
            {
                "environment": "production",
                "database_url": "postgresql://example",
                "log_json": True,
                "docs_enabled": False,
                "internal_auth_secret": "short",
            }
        )


def test_valid_production_configuration() -> None:
    settings = Settings.model_validate(
        {
            "environment": "production",
            "database_url": "postgresql://example",
            "log_json": True,
            "docs_enabled": False,
            "internal_auth_secret": "production-secret-with-at-least-32-characters",
            "twelve_data_api_key": "production-twelve-data-server-key",
            "market_evidence_source_mode": "canonical",
            "portfolio_history_runtime_enabled": True,
            "scheduled_snapshot_refresh_runner_enabled": True,
        }
    )

    assert settings.environment == "production"
    assert settings.log_json is True
    assert settings.docs_enabled is False
    assert settings.market_evidence_source_mode == "canonical"
    assert settings.portfolio_history_runtime_enabled is True
    assert settings.scheduled_snapshot_refresh_runner_enabled is True
    assert "production-twelve-data-server-key" not in repr(settings)
