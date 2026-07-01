from fastapi import APIRouter

from app.api.v1 import (
    backtests,
    data_sources,
    etfs,
    evaluation,
    factors,
    monitoring,
    refresh,
    rotation,
    signals,
    status,
)

router = APIRouter()
router.include_router(status.router, tags=["status"])
router.include_router(data_sources.router, prefix="/data-sources", tags=["data-sources"])
router.include_router(etfs.router, prefix="/etfs", tags=["etfs"])
router.include_router(factors.router, prefix="/factors", tags=["factors"])
router.include_router(evaluation.router, prefix="/evaluation", tags=["evaluation"])
router.include_router(signals.router, prefix="/signals", tags=["signals"])
router.include_router(backtests.router, prefix="/backtests", tags=["backtests"])
router.include_router(monitoring.router, prefix="/monitoring", tags=["monitoring"])
router.include_router(rotation.router, prefix="/rotation", tags=["rotation"])
router.include_router(refresh.router, tags=["refresh"])
