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

    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_production_settings(self) -> Self:
        if self.environment != "production":
            return self

        errors: list[str] = []
        if not self.database_url:
            errors.append("DATABASE_URL is required")
        if not self.log_json:
            errors.append("LOG_JSON must be true")
        if self.docs_enabled:
            errors.append("DOCS_ENABLED must be false")

        if errors:
            raise ValueError("Invalid production settings: " + "; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
