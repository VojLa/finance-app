"""Safe, provider-independent failure metadata for health and retry decisions."""

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from app.db.models.enums import MarketDataFailureReason
from app.modules.market_data.models import MarketEvidenceStateError

_RETRYABLE = frozenset(
    {
        MarketDataFailureReason.timeout,
        MarketDataFailureReason.server_error,
        MarketDataFailureReason.incomplete_response,
        MarketDataFailureReason.rate_limit,
    }
)


class ProviderFailure(MarketEvidenceStateError):
    def __init__(
        self,
        reason: MarketDataFailureReason,
        *,
        retry_after: datetime | None = None,
    ) -> None:
        if not isinstance(reason, MarketDataFailureReason):
            raise ValueError("invalid provider failure reason")
        if retry_after is not None and reason is not MarketDataFailureReason.rate_limit:
            raise ValueError("retry_after requires rate_limit")
        super().__init__()
        self.reason = reason
        self.retryable = reason in _RETRYABLE
        self.retry_after = retry_after


def failure_for_status(status_code: int, retry_after_header: str | None = None) -> ProviderFailure:
    if status_code == 429:
        reason = MarketDataFailureReason.rate_limit
    elif status_code in (408, 504):
        reason = MarketDataFailureReason.timeout
    elif status_code == 404:
        reason = MarketDataFailureReason.unknown_symbol
    elif status_code in (400, 401, 403, 422):
        reason = MarketDataFailureReason.provider_identity_conflict
    elif 500 <= status_code <= 599:
        reason = MarketDataFailureReason.server_error
    else:
        reason = MarketDataFailureReason.incomplete_response
    retry_after = None
    if reason is MarketDataFailureReason.rate_limit and retry_after_header:
        try:
            seconds = int(retry_after_header)
            if 0 < seconds <= 86_400:
                retry_after = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=seconds)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(retry_after_header)
                if parsed.tzinfo is not None and parsed > datetime.now(UTC):
                    retry_after = parsed.astimezone(UTC).replace(tzinfo=None)
            except (TypeError, ValueError, OverflowError):
                pass
    return ProviderFailure(reason, retry_after=retry_after)
