from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.auth.api import router as auth_router
from app.modules.accounts.api import router as accounts_router
from app.modules.accounts.invitations import router as account_invitation_router
from app.modules.dashboard_snapshot.api import router as dashboard_snapshot_router
from app.modules.holdings.api import router as holdings_router
from app.modules.imports.api import router as imports_router
from app.modules.net_worth.api import router as net_worth_router
from app.modules.portfolio.api import router as portfolio_router
from app.modules.portfolio_history.api import router as portfolio_history_router
from app.modules.portfolio_snapshot.api import router as portfolio_snapshot_router
from app.modules.portfolio_snapshot.multi_account_api import (
    router as multi_account_portfolio_snapshot_router,
)
from app.modules.snapshot_refresh.api import router as snapshot_refresh_router
from app.modules.snapshots.api import router as snapshots_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(accounts_router)
api_router.include_router(account_invitation_router)
api_router.include_router(holdings_router)
api_router.include_router(imports_router)
api_router.include_router(net_worth_router)
api_router.include_router(portfolio_router)
api_router.include_router(portfolio_history_router)
api_router.include_router(portfolio_snapshot_router)
api_router.include_router(multi_account_portfolio_snapshot_router)
api_router.include_router(dashboard_snapshot_router)
api_router.include_router(snapshots_router)
api_router.include_router(snapshot_refresh_router)

legacy_router = APIRouter(include_in_schema=False)
legacy_router.include_router(health_router)
legacy_router.include_router(portfolio_router)
