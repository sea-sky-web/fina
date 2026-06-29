from fastapi import APIRouter, Query

from app.models import RefreshResult
from app.services.refresh_service import refresh_top_etfs

router = APIRouter()


@router.post("/refresh/top-etfs", response_model=RefreshResult)
def refresh_top_etf_data(
    limit: int = Query(default=100, ge=1, le=100),
    lookback_days: int = Query(default=365, ge=30, le=3650),
    rebuild_factors: bool = Query(default=True),
) -> RefreshResult:
    return refresh_top_etfs(
        limit=limit,
        lookback_days=lookback_days,
        rebuild_factor_data=rebuild_factors,
    )
