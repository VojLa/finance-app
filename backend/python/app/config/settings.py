from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    app_name: str = "Finance App Backend"
    app_version: str = "0.1.0"
    environment: Environment = "development"
    database_url: str | None = None
    log_level: LogLevel = "INFO"
    log_json: bool = False
    docs_enabled: bool = True
    internal_auth_secret: str | None = None
    internal_auth_issuer: str = "finance-app-next"
    internal_auth_audience: str = "finance-app-python"
    internal_auth_clock_skew_seconds: int = 30

    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_settings(self) -> Self:
        errors: list[str] = []
        if self.internal_auth_clock_skew_seconds < 0:
            errors.append("INTERNAL_AUTH_CLOCK_SKEW_SECONDS must be non-negative")

        if self.environment == "production":
            if not self.database_url:
                errors.append("DATABASE_URL is required")
            if not self.log_json:
                errors.append("LOG_JSON must be true")
            if self.docs_enabled:
                errors.append("DOCS_ENABLED must be false")
            if not self.internal_auth_secret:
                errors.append("INTERNAL_AUTH_SECRET is required")
            elif len(self.internal_auth_secret) < 32:
                errors.append("INTERNAL_AUTH_SECRET must contain at least 32 characters")

        if errors:
            raise ValueError("Invalid settings: " + "; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
