from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.models import BacktestResult, WalkForwardResultModel
from app.services.backtest_service import (
    run_research_signal_backtest,
    run_walk_forward_analysis,
)

router = APIRouter()


@router.get("/research-signal", response_model=BacktestResult)
def research_signal_backtest(
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    top_n: Annotated[int, Query(ge=1, le=50)] = 10,
    rebalance: Annotated[str, Query()] = "monthly",
    cost_bps: Annotated[float, Query(ge=0, le=100)] = 5.0,
    benchmark: Annotated[str, Query()] = "510300.SH",
) -> BacktestResult:
    return run_research_signal_backtest(
        start=start,
        end=end,
        top_n=top_n,
        rebalance=rebalance,
        cost_bps=cost_bps,
        benchmark=benchmark,
    )


@router.get("/walk-forward", response_model=WalkForwardResultModel)
def walk_forward(
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    train_months: Annotated[int, Query(ge=6, le=60)] = 24,
    test_months: Annotated[int, Query(ge=3, le=24)] = 6,
    step_months: Annotated[int, Query(ge=1, le=12)] = 6,
    top_n: Annotated[int, Query(ge=1, le=50)] = 10,
    cost_bps: Annotated[float, Query(ge=0, le=100)] = 5.0,
) -> WalkForwardResultModel:
    return run_walk_forward_analysis(
        start=start,
        end=end,
        train_months=train_months,
        test_months=test_months,
        step_months=step_months,
        top_n=top_n,
        cost_bps=cost_bps,
    )
