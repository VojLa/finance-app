import pytest

from app.config.settings import Settings


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        environment="test",
        database_url=None,
        log_level="ERROR",
        log_json=False,
        docs_enabled=True,
        _env_file=None,
    )
