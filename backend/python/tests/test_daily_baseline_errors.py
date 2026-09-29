from app.modules.daily_baselines.service import DailyBaselineUnavailableError
from app.shared.errors import ApplicationError


def test_unavailable_daily_baseline_is_a_safe_conflict_error() -> None:
    error = DailyBaselineUnavailableError()

    assert isinstance(error, ApplicationError)
    assert error.code == "daily_snapshot_baseline_unavailable"
    assert error.message == "Daily snapshot baseline evidence is unavailable."
    assert error.status_code == 409
