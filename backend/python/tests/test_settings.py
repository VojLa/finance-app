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


def test_test_environment_starts_without_auth_secret() -> None:
    settings = Settings(environment="test", internal_auth_secret=None, _env_file=None)

    assert settings.internal_auth_secret is None


def test_negative_auth_clock_skew_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be non-negative"):
        Settings(internal_auth_clock_skew_seconds=-1, _env_file=None)


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"environment": "staging"})


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
        }
    )

    assert settings.environment == "production"
    assert settings.log_json is True
    assert settings.docs_enabled is False
