from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    ResearchSignal,
    SignalPerformanceModel,
    SignalSnapshotResult,
)
from app.monitoring.signal_tracker import (
    recent_signal_performance,
    take_signal_snapshot,
)
from app.services.signal_service import get_research_signal, list_research_signals

router = APIRouter()


@router.get("", response_model=list[ResearchSignal])
def signals(
    signal_date: Annotated[date | None, Query(alias="date")] = None,
    theme: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[ResearchSignal]:
    return list_research_signals(signal_date=signal_date, theme=theme, limit=limit)


@router.get("/performance", response_model=list[SignalPerformanceModel])
def signal_performance(
    lookback_days: Annotated[int, Query(ge=30, le=365)] = 90,
    horizon_days: Annotated[int, Query(ge=5, le=120)] = 20,
) -> list[SignalPerformanceModel]:
    results = recent_signal_performance(
        lookback_days=lookback_days,
        horizon_days=horizon_days,
    )
    return [
        SignalPerformanceModel(
            snapshot_date=r.snapshot_date,
            horizon_days=r.horizon_days,
            top_mean_return=r.top_mean_return,
            benchmark_return=r.benchmark_return,
            excess_return=r.excess_return,
            hit_rate=r.hit_rate,
            score_return_corr=r.score_return_corr,
            top_symbols=r.top_symbols,
            data_notes=r.data_notes,
        )
        for r in results
    ]


@router.get("/{symbol}", response_model=ResearchSignal)
def signal_detail(
    symbol: str,
    signal_date: Annotated[date | None, Query(alias="date")] = None,
) -> ResearchSignal:
    signal = get_research_signal(symbol=symbol, signal_date=signal_date)
    if signal is None:
        raise HTTPException(status_code=404, detail="Research signal not found")
    return signal


@router.post("/snapshot", response_model=SignalSnapshotResult)
def save_signal_snapshot(
    top_n: Annotated[int, Query(ge=5, le=100)] = 20,
) -> SignalSnapshotResult:
    signals = list_research_signals(limit=top_n)
    if not signals:
        return SignalSnapshotResult(ok=False, message="无信号数据，跳过快照。")
    raw = [
        {
            "symbol": s.symbol,
            "name": s.name,
            "theme": s.theme,
            "research_score": s.research_score,
        }
        for s in signals
    ]
    result = take_signal_snapshot(
        signal_date=signals[0].date,
        signals=raw,
        top_n=top_n,
    )
    return SignalSnapshotResult(**result)
