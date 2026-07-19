from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.auth.api import router as auth_router
from app.modules.accounts.api import router as accounts_router
from app.modules.portfolio.api import router as portfolio_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(accounts_router)
api_router.include_router(portfolio_router)

legacy_router = APIRouter(include_in_schema=False)
legacy_router.include_router(health_router)
legacy_router.include_router(portfolio_router)
