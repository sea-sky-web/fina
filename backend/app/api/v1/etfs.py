from datetime import date

from fastapi import APIRouter, Query

from app.models import EtfBasic, EtfDailyBar
from app.services.etf_service import get_etf_daily, list_etfs

router = APIRouter()


@router.get("", response_model=list[EtfBasic])
def etfs(limit: int = Query(default=100, ge=1, le=1000)) -> list[EtfBasic]:
    return list_etfs(limit=limit)


@router.get("/{symbol}/daily", response_model=list[EtfDailyBar])
def etf_daily(
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=250, ge=1, le=5000),
) -> list[EtfDailyBar]:
    return get_etf_daily(symbol=symbol, start=start, end=end, limit=limit)
