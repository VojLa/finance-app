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
        internal_auth_secret="test-secret-that-is-long-enough-for-auth",
        _env_file=None,
    )
