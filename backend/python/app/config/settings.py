from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
MarketEvidenceSourceMode = Literal["canonical", "local_free"]


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
    coingecko_price_base_url: str = "https://api.coingecko.com/api/v3/simple/price"
    coingecko_history_base_url: str = "https://api.coingecko.com/api/v3/coins"
    coingecko_price_timeout_seconds: float = 10.0
    coingecko_price_max_response_bytes: int = 1_048_576
    coingecko_price_user_agent: str = "finance-app/0.1"
    coingecko_demo_api_key: SecretStr | None = None
    coingecko_pro_api_key: SecretStr | None = None
    twelve_data_quote_base_url: str = "https://api.twelvedata.com/quote"
    twelve_data_fx_base_url: str = "https://api.twelvedata.com/time_series"
    twelve_data_timeout_seconds: float = 10.0
    twelve_data_max_response_bytes: int = 1_048_576
    twelve_data_user_agent: str = "finance-app/0.1"
    twelve_data_api_key: SecretStr | None = None
    market_evidence_source_mode: MarketEvidenceSourceMode = "canonical"
    yahoo_finance_chart_base_url: str = "https://query1.finance.yahoo.com/v8/finance/chart"
    yahoo_finance_timeout_seconds: float = 10.0
    yahoo_finance_max_response_bytes: int = 1_048_576
    yahoo_finance_user_agent: str = "finance-app/0.1"
    background_jobs_enabled: bool = False
    background_job_poll_seconds: float = 0.75
    background_job_lease_seconds: int = 300
    background_job_heartbeat_seconds: int = 15
    background_job_shutdown_grace_seconds: float = 5.0
    portfolio_history_runtime_enabled: bool = False
    portfolio_history_worker_id: str = "portfolio-history-api"
    portfolio_history_worker_poll_seconds: float = 1.0
    portfolio_history_worker_lease_seconds: int = 300
    portfolio_history_worker_heartbeat_seconds: int = 15
    portfolio_history_scheduler_poll_seconds: float = 30.0
    portfolio_history_shutdown_grace_seconds: float = 5.0
    scheduled_snapshot_refresh_runner_enabled: bool = False
    scheduled_snapshot_refresh_interval_seconds: float = 300.0
    scheduled_snapshot_refresh_shutdown_grace_seconds: float = 5.0

    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_settings(self) -> Self:
        if self.internal_auth_clock_skew_seconds < 0:
            raise ValueError("INTERNAL_AUTH_CLOCK_SKEW_SECONDS must be non-negative")
        price_url = urlsplit(self.coingecko_price_base_url)
        if (
            price_url.scheme != "https"
            or not price_url.hostname
            or price_url.username is not None
            or price_url.password is not None
            or bool(price_url.query)
            or bool(price_url.fragment)
            or any(character.isspace() for character in self.coingecko_price_base_url)
        ):
            raise ValueError(
                "COINGECKO_PRICE_BASE_URL must be an absolute credential-free HTTPS URL"
            )
        history_url = urlsplit(self.coingecko_history_base_url)
        if (
            history_url.scheme != "https"
            or not history_url.hostname
            or history_url.username is not None
            or history_url.password is not None
            or bool(history_url.query)
            or bool(history_url.fragment)
            or self.coingecko_history_base_url.endswith("/")
            or any(character.isspace() for character in self.coingecko_history_base_url)
        ):
            raise ValueError(
                "COINGECKO_HISTORY_BASE_URL must be an absolute credential-free HTTPS URL"
            )
        if not 0 < self.coingecko_price_timeout_seconds <= 120:
            raise ValueError(
                "COINGECKO_PRICE_TIMEOUT_SECONDS must be greater than zero and at most 120"
            )
        if not 0 < self.coingecko_price_max_response_bytes <= 10_485_760:
            raise ValueError(
                "COINGECKO_PRICE_MAX_RESPONSE_BYTES must be greater than zero and at most 10485760"
            )
        if (
            not self.coingecko_price_user_agent
            or self.coingecko_price_user_agent != self.coingecko_price_user_agent.strip()
            or "\r" in self.coingecko_price_user_agent
            or "\n" in self.coingecko_price_user_agent
            or len(self.coingecko_price_user_agent) > 256
        ):
            raise ValueError("COINGECKO_PRICE_USER_AGENT must be a safe non-empty value")
        if self.coingecko_demo_api_key is not None:
            demo_key = self.coingecko_demo_api_key.get_secret_value()
            if (
                not demo_key
                or demo_key != demo_key.strip()
                or "\r" in demo_key
                or "\n" in demo_key
                or len(demo_key) > 512
            ):
                raise ValueError("COINGECKO_DEMO_API_KEY must be a safe non-empty value")
        if self.coingecko_pro_api_key is not None:
            pro_key = self.coingecko_pro_api_key.get_secret_value()
            if (
                not pro_key
                or pro_key != pro_key.strip()
                or "\r" in pro_key
                or "\n" in pro_key
                or len(pro_key) > 512
            ):
                raise ValueError("COINGECKO_PRO_API_KEY must be a safe non-empty value")
        if self.coingecko_demo_api_key is not None and self.coingecko_pro_api_key is not None:
            raise ValueError(
                "COINGECKO_DEMO_API_KEY and COINGECKO_PRO_API_KEY are mutually exclusive"
            )
        quote_url = urlsplit(self.twelve_data_quote_base_url)
        if (
            quote_url.scheme != "https"
            or not quote_url.hostname
            or quote_url.username is not None
            or quote_url.password is not None
            or bool(quote_url.query)
            or bool(quote_url.fragment)
            or any(character.isspace() for character in self.twelve_data_quote_base_url)
        ):
            raise ValueError(
                "TWELVE_DATA_QUOTE_BASE_URL must be an absolute credential-free HTTPS URL"
            )
        fx_url = urlsplit(self.twelve_data_fx_base_url)
        if (
            fx_url.scheme != "https"
            or not fx_url.hostname
            or fx_url.username is not None
            or fx_url.password is not None
            or bool(fx_url.query)
            or bool(fx_url.fragment)
            or any(character.isspace() for character in self.twelve_data_fx_base_url)
        ):
            raise ValueError(
                "TWELVE_DATA_FX_BASE_URL must be an absolute credential-free HTTPS URL"
            )
        if not 0 < self.twelve_data_timeout_seconds <= 120:
            raise ValueError(
                "TWELVE_DATA_TIMEOUT_SECONDS must be greater than zero and at most 120"
            )
        if not 0 < self.twelve_data_max_response_bytes <= 10_485_760:
            raise ValueError(
                "TWELVE_DATA_MAX_RESPONSE_BYTES must be greater than zero and at most 10485760"
            )
        if (
            not self.twelve_data_user_agent
            or self.twelve_data_user_agent != self.twelve_data_user_agent.strip()
            or "\r" in self.twelve_data_user_agent
            or "\n" in self.twelve_data_user_agent
            or len(self.twelve_data_user_agent) > 256
        ):
            raise ValueError("TWELVE_DATA_USER_AGENT must be a safe non-empty value")
        if self.twelve_data_api_key is not None:
            api_key = self.twelve_data_api_key.get_secret_value()
            if (
                not api_key
                or api_key != api_key.strip()
                or "\r" in api_key
                or "\n" in api_key
                or len(api_key) > 512
            ):
                raise ValueError("TWELVE_DATA_API_KEY must be a safe non-empty value")
        yahoo_chart_url = urlsplit(self.yahoo_finance_chart_base_url)
        if (
            yahoo_chart_url.scheme != "https"
            or not yahoo_chart_url.hostname
            or yahoo_chart_url.username is not None
            or yahoo_chart_url.password is not None
            or bool(yahoo_chart_url.query)
            or bool(yahoo_chart_url.fragment)
            or self.yahoo_finance_chart_base_url.endswith("/")
            or any(character.isspace() for character in self.yahoo_finance_chart_base_url)
        ):
            raise ValueError(
                "YAHOO_FINANCE_CHART_BASE_URL must be an absolute credential-free HTTPS URL"
            )
        if not 0 < self.yahoo_finance_timeout_seconds <= 120:
            raise ValueError(
                "YAHOO_FINANCE_TIMEOUT_SECONDS must be greater than zero and at most 120"
            )
        if not 0 < self.yahoo_finance_max_response_bytes <= 10_485_760:
            raise ValueError(
                "YAHOO_FINANCE_MAX_RESPONSE_BYTES must be greater than zero and at most 10485760"
            )
        if (
            not self.yahoo_finance_user_agent
            or self.yahoo_finance_user_agent != self.yahoo_finance_user_agent.strip()
            or "\r" in self.yahoo_finance_user_agent
            or "\n" in self.yahoo_finance_user_agent
            or len(self.yahoo_finance_user_agent) > 256
        ):
            raise ValueError("YAHOO_FINANCE_USER_AGENT must be a safe non-empty value")
        if not 0.1 <= self.background_job_poll_seconds <= 60:
            raise ValueError("BACKGROUND_JOB_POLL_SECONDS must be between 0.1 and 60")
        if not 30 <= self.background_job_lease_seconds <= 1800:
            raise ValueError("BACKGROUND_JOB_LEASE_SECONDS must be between 30 and 1800")
        if not 1 <= self.background_job_heartbeat_seconds < self.background_job_lease_seconds:
            raise ValueError(
                "BACKGROUND_JOB_HEARTBEAT_SECONDS must be positive and shorter than the lease"
            )
        if not 0 <= self.background_job_shutdown_grace_seconds <= 60:
            raise ValueError("BACKGROUND_JOB_SHUTDOWN_GRACE_SECONDS must be between zero and 60")
        if (
            not self.portfolio_history_worker_id
            or self.portfolio_history_worker_id != self.portfolio_history_worker_id.strip()
            or len(self.portfolio_history_worker_id) > 163
            or any(character in self.portfolio_history_worker_id for character in "\r\n\0")
        ):
            raise ValueError("PORTFOLIO_HISTORY_WORKER_ID must be a safe non-empty value")
        if not 0.1 <= self.portfolio_history_worker_poll_seconds <= 60:
            raise ValueError("PORTFOLIO_HISTORY_WORKER_POLL_SECONDS must be between 0.1 and 60")
        if not 30 <= self.portfolio_history_worker_lease_seconds <= 1800:
            raise ValueError("PORTFOLIO_HISTORY_WORKER_LEASE_SECONDS must be between 30 and 1800")
        if not (
            1
            <= self.portfolio_history_worker_heartbeat_seconds
            < self.portfolio_history_worker_lease_seconds
        ):
            raise ValueError(
                "PORTFOLIO_HISTORY_WORKER_HEARTBEAT_SECONDS must be positive and shorter "
                "than the lease"
            )
        if not 0.1 <= self.portfolio_history_scheduler_poll_seconds <= 300:
            raise ValueError("PORTFOLIO_HISTORY_SCHEDULER_POLL_SECONDS must be between 0.1 and 300")
        if not 0 <= self.portfolio_history_shutdown_grace_seconds <= 60:
            raise ValueError("PORTFOLIO_HISTORY_SHUTDOWN_GRACE_SECONDS must be between zero and 60")
        if not 30 <= self.scheduled_snapshot_refresh_interval_seconds <= 3600:
            raise ValueError(
                "SCHEDULED_SNAPSHOT_REFRESH_INTERVAL_SECONDS must be between 30 and 3600"
            )
        if not 0 <= self.scheduled_snapshot_refresh_shutdown_grace_seconds <= 60:
            raise ValueError(
                "SCHEDULED_SNAPSHOT_REFRESH_SHUTDOWN_GRACE_SECONDS must be between zero and 60"
            )
        if self.portfolio_history_runtime_enabled and self.database_url is None:
            raise ValueError(
                "DATABASE_URL is required when the portfolio history runtime is enabled"
            )
        if self.scheduled_snapshot_refresh_runner_enabled and self.database_url is None:
            raise ValueError("DATABASE_URL is required when scheduled snapshot refresh is enabled")
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
        if self.twelve_data_api_key is None:
            errors.append("TWELVE_DATA_API_KEY is required")
        if self.market_evidence_source_mode != "canonical":
            errors.append("MARKET_EVIDENCE_SOURCE_MODE must be canonical in production")
        if self.background_jobs_enabled and self.database_url is None:
            errors.append("DATABASE_URL is required when background jobs are enabled")
        if not self.portfolio_history_runtime_enabled:
            errors.append("PORTFOLIO_HISTORY_RUNTIME_ENABLED must be true")
        if not self.scheduled_snapshot_refresh_runner_enabled:
            errors.append("SCHEDULED_SNAPSHOT_REFRESH_RUNNER_ENABLED must be true")
        if self.scheduled_snapshot_refresh_runner_enabled and self.database_url is None:
            errors.append("DATABASE_URL is required when scheduled snapshot refresh is enabled")

        if errors:
            raise ValueError("Invalid production settings: " + "; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
