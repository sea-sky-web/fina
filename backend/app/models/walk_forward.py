from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.etf import BacktestEquityPoint, BacktestMetrics


class WalkForwardConfigModel(BaseModel):
    train_months: int = 24
    test_months: int = 6
    step_months: int = 6
    top_n: int = 10
    cost_bps: float = 5.0


class WalkForwardWindowModel(BaseModel):
    train_start: dt_date
    train_end: dt_date
    test_start: dt_date
    test_end: dt_date
    selected_factors: list[str] = Field(default_factory=list)
    factor_weights: dict[str, float] = Field(default_factory=dict)
    train_icir: dict[str, float | None] = Field(default_factory=dict)
    test_metrics: BacktestMetrics
    test_equity_curve: list[BacktestEquityPoint] = Field(default_factory=list)


class WalkForwardResultModel(BaseModel):
    config: WalkForwardConfigModel
    windows: list[WalkForwardWindowModel] = Field(default_factory=list)
    oos_equity_curve: list[BacktestEquityPoint] = Field(default_factory=list)
    oos_metrics: BacktestMetrics
    is_metrics: BacktestMetrics
    factor_stability: float = 0.0
    weight_stability: dict[str, float | None] = Field(default_factory=dict)
    overfit_warning: str = ""
    data_notes: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None
