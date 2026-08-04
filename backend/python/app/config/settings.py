from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlsplit

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
    cnb_fx_base_url: str = (
        "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/"
        "kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.xml"
    )
    cnb_fx_timeout_seconds: float = 10.0
    cnb_fx_max_response_bytes: int = 1_048_576
    cnb_fx_user_agent: str = "finance-app/0.1"

    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_settings(self) -> Self:
        if self.internal_auth_clock_skew_seconds < 0:
            raise ValueError("INTERNAL_AUTH_CLOCK_SKEW_SECONDS must be non-negative")
        url = urlsplit(self.cnb_fx_base_url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or bool(url.query)
            or bool(url.fragment)
            or any(character.isspace() for character in self.cnb_fx_base_url)
        ):
            raise ValueError("CNB_FX_BASE_URL must be an absolute credential-free HTTPS URL")
        if not 0 < self.cnb_fx_timeout_seconds <= 120:
            raise ValueError("CNB_FX_TIMEOUT_SECONDS must be greater than zero and at most 120")
        if not 0 < self.cnb_fx_max_response_bytes <= 10_485_760:
            raise ValueError(
                "CNB_FX_MAX_RESPONSE_BYTES must be greater than zero and at most 10485760"
            )
        if (
            not self.cnb_fx_user_agent
            or self.cnb_fx_user_agent != self.cnb_fx_user_agent.strip()
            or "\r" in self.cnb_fx_user_agent
            or "\n" in self.cnb_fx_user_agent
            or len(self.cnb_fx_user_agent) > 256
        ):
            raise ValueError("CNB_FX_USER_AGENT must be a safe non-empty value")
        if self.environment != "production":
            return self

        errors: list[str] = []
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
            raise ValueError("Invalid production settings: " + "; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
