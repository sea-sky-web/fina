from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    FactorEvaluationReport,
    FactorICStats,
    FactorPoolEvaluationReport,
    FactorQuantileReturns,
)
from app.services.evaluation_service import (
    calculate_ic_stats,
    calculate_quantile_returns,
    default_horizons,
    generate_factor_evaluation_report,
    generate_factor_pool_report,
)

router = APIRouter()


def _parse_horizons(raw: str | None) -> list[int]:
    if not raw:
        return default_horizons()
    horizons: list[int] = []
    for item in raw.split(","):
        try:
            value = int(item.strip())
        except ValueError:
            continue
        if value > 0 and value <= 252 and value not in horizons:
            horizons.append(value)
    return horizons or default_horizons()


@router.get("/pool-report", response_model=FactorPoolEvaluationReport)
def pool_report(
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    horizons: Annotated[str | None, Query()] = None,
    processed: Annotated[bool, Query()] = True,
) -> FactorPoolEvaluationReport:
    return generate_factor_pool_report(
        start=start,
        end=end,
        horizons=_parse_horizons(horizons),
        processed=processed,
    )


@router.get("/{factor_name}/report", response_model=FactorEvaluationReport)
def factor_report(
    factor_name: str,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    horizons: Annotated[str | None, Query()] = None,
    processed: Annotated[bool, Query()] = True,
) -> FactorEvaluationReport:
    report = generate_factor_evaluation_report(
        factor_name,
        start=start,
        end=end,
        horizons=_parse_horizons(horizons),
        processed=processed,
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Factor evaluation report not found")
    return report


@router.get("/{factor_name}/ic-series", response_model=FactorICStats)
def ic_series(
    factor_name: str,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    horizon: Annotated[int, Query(ge=1, le=252)] = 20,
    processed: Annotated[bool, Query()] = True,
) -> FactorICStats:
    return calculate_ic_stats(
        factor_name,
        start=start,
        end=end,
        horizon=horizon,
        horizons=[horizon],
        processed=processed,
    )


@router.get("/{factor_name}/quantile-chart", response_model=FactorQuantileReturns)
def quantile_chart(
    factor_name: str,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    horizon: Annotated[int, Query(ge=1, le=252)] = 20,
    processed: Annotated[bool, Query()] = True,
) -> FactorQuantileReturns:
    return calculate_quantile_returns(
        factor_name,
        start=start,
        end=end,
        horizon=horizon,
        processed=processed,
    )


@router.post("/run", response_model=FactorPoolEvaluationReport)
def run_evaluation(
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    horizons: Annotated[str | None, Query()] = None,
    processed: Annotated[bool, Query()] = True,
) -> FactorPoolEvaluationReport:
    return generate_factor_pool_report(
        start=start,
        end=end,
        horizons=_parse_horizons(horizons),
        processed=processed,
    )
