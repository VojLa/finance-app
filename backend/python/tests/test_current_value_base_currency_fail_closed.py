from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.modules.current_value.service import (
    CurrentValueService,
    CurrentValueUnavailableError,
    ReadCurrentPortfolioCommand,
)
from app.modules.daily_baselines.service import (
    DailyBaselineUnavailableError,
    DailySnapshotBaselineService,
)


@pytest.mark.asyncio
async def test_current_value_never_continues_when_base_currency_makes_baseline_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    cast(AsyncMock, session.in_transaction).return_value = False
    market_factory = Mock(side_effect=AssertionError("market refresh must not run"))
    service = CurrentValueService(
        session,
        Settings(environment="test", _env_file=None),
        market_service_factory=market_factory,
    )
    load_import_fence = AsyncMock(return_value=())
    monkeypatch.setattr(service, "_load_active_import_account_ids", load_import_fence)
    select_baseline = AsyncMock(side_effect=DailyBaselineUnavailableError())
    monkeypatch.setattr(
        DailySnapshotBaselineService,
        "select_latest_valid",
        select_baseline,
    )

    with pytest.raises(CurrentValueUnavailableError):
        await service.read_portfolio(
            ReadCurrentPortfolioCommand(
                principal=AuthenticatedPrincipal(
                    user_id="user-a",
                    email="user-a@example.test",
                )
            )
        )

    assert select_baseline.await_count == 2
    assert load_import_fence.await_count == 2
    market_factory.assert_not_called()
