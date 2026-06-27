from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.models import FactorDiagnostics, FactorHistoryPoint, FactorScore
from app.services.factor_service import (
    get_factor_definitions,
    get_factor_diagnostics,
    get_factor_history,
    list_factor_scores,
    rebuild_factors,
)

router = APIRouter()


@router.get("/diagnostics", response_model=FactorDiagnostics)
def factor_diagnostics(
    name: Annotated[str, Query()] = "momentum_60d",
    factor_date: Annotated[date | None, Query(alias="date")] = None,
    horizon: Annotated[int, Query(ge=1, le=120)] = 20,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    processed: Annotated[bool, Query()] = False,
) -> FactorDiagnostics:
    diagnostics = get_factor_diagnostics(
        factor_name=name,
        factor_date=factor_date,
        horizon=horizon,
        limit=limit,
        processed=processed,
    )
    if diagnostics is None:
        raise HTTPException(status_code=404, detail="Factor diagnostics not found")
    return diagnostics


@router.get("/history", response_model=list[FactorHistoryPoint])
def factor_history(
    symbol: Annotated[str, Query()],
    name: Annotated[str, Query()] = "momentum_60d",
    processed: Annotated[bool, Query()] = False,
) -> list[FactorHistoryPoint]:
    return get_factor_history(symbol=symbol, factor_name=name, processed=processed)


@router.get("", response_model=list[FactorScore])
def factors(
    name: Annotated[str, Query()] = "momentum_60d",
    factor_date: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    processed: Annotated[bool, Query()] = False,
) -> list[FactorScore]:
    return list_factor_scores(
        factor_name=name,
        factor_date=factor_date,
        limit=limit,
        processed=processed,
    )


@router.get("/definitions")
def factor_definitions() -> list[dict[str, str]]:
    return get_factor_definitions()


@router.post("/rebuild")
def rebuild() -> dict[str, object]:
    return rebuild_factors()
