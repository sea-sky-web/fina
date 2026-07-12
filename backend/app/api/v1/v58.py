from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.models import V58Config, V58SignalReport
from app.services.v58_signal_service import generate_v58_signal
from app.services.v58_state import reset_state

router = APIRouter()


@router.get("/signal", response_model=V58SignalReport)
def v58_signal(
    signal_date: Annotated[date | None, Query(alias="date")] = None,
) -> V58SignalReport:
    """Generate V58 sector rotation signal for the given date."""
    return generate_v58_signal(signal_date=signal_date)


@router.get("/config", response_model=V58Config)
def v58_config() -> V58Config:
    """Return current V58 strategy configuration."""
    return V58Config()


@router.post("/reset-state")
def v58_reset() -> dict[str, str]:
    """Reset V58 portfolio state (entry prices, cooldowns, holdings)."""
    reset_state()
    return {"status": "ok", "message": "V58 portfolio state reset"}
