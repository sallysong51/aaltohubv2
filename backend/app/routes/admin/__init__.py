"""Admin routes — split into sub-modules for maintainability."""
from fastapi import APIRouter

from .groups import router as groups_router
from .messages import router as messages_router
from .crawler import router as crawler_router
from .users import router as users_router
from .credentials import router as credentials_router
from .system_diagnostics import router as system_diagnostics_router

router = APIRouter(prefix="/admin", tags=["Admin"])

router.include_router(groups_router)
router.include_router(messages_router)
router.include_router(crawler_router)
router.include_router(users_router)
router.include_router(credentials_router)
router.include_router(system_diagnostics_router)
