import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_development_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.log_json is False
    assert settings.docs_enabled is True


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"environment": "staging"})


def test_production_requires_safe_configuration() -> None:
    with pytest.raises(ValidationError, match="Invalid production settings"):
        Settings.model_validate({"environment": "production"})


def test_valid_production_configuration() -> None:
    settings = Settings.model_validate(
        {
            "environment": "production",
            "database_url": "postgresql://example",
            "log_json": True,
            "docs_enabled": False,
        }
    )

    assert settings.environment == "production"
    assert settings.log_json is True
    assert settings.docs_enabled is False
