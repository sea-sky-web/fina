from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime

from pydantic import BaseModel, Field


class FactorICPoint(BaseModel):
    date: dt_date
    ic_value: float


class FactorICStats(BaseModel):
    factor_name: str
    period_start: dt_date | None = None
    period_end: dt_date | None = None
    num_periods: int = 0
    rank_ic_mean: float | None = None
    rank_ic_std: float | None = None
    icir: float | None = None
    ic_pos_ratio: float | None = None
    ic_t_stat: float | None = None
    ic_series: list[FactorICPoint] = Field(default_factory=list)
    ic_by_horizon: dict[int, float | None] = Field(default_factory=dict)


class FactorQuantilePoint(BaseModel):
    date: dt_date
    returns: dict[str, float | None] = Field(default_factory=dict)


class FactorQuantileReturns(BaseModel):
    factor_name: str
    horizon_days: int
    num_quantiles: int = 5
    quantile_returns: dict[str, float | None] = Field(default_factory=dict)
    spread: float | None = None
    is_monotonic: bool = False
    quantile_series: list[FactorQuantilePoint] = Field(default_factory=list)


class RedundantFactorPair(BaseModel):
    factor_a: str
    factor_b: str
    correlation: float


class FactorCorrelationMatrix(BaseModel):
    date: dt_date | None = None
    factor_names: list[str] = Field(default_factory=list)
    matrix: list[list[float | None]] = Field(default_factory=list)
    redundant_pairs: list[RedundantFactorPair] = Field(default_factory=list)


class FactorTurnoverStats(BaseModel):
    factor_name: str
    rank_autocorr: dict[int, float | None] = Field(default_factory=dict)
    avg_turnover: float | None = None
    migration_matrix: list[list[float | None]] = Field(default_factory=list)


class FactorEvaluationReport(BaseModel):
    factor_name: str
    generated_at: datetime
    period_start: dt_date | None = None
    period_end: dt_date | None = None
    num_assets_avg: float = 0.0
    ic: FactorICStats
    quantile_returns: dict[int, FactorQuantileReturns] = Field(default_factory=dict)
    correlations: FactorCorrelationMatrix | None = None
    turnover: FactorTurnoverStats | None = None
    warnings: list[str] = Field(default_factory=list)
    overall_verdict: str = "待观察"


class FactorClusterGroup(BaseModel):
    group: str
    factors: list[str] = Field(default_factory=list)


class FactorPoolEvaluationReport(BaseModel):
    generated_at: datetime
    individual_reports: list[FactorEvaluationReport] = Field(default_factory=list)
    correlation_matrix: FactorCorrelationMatrix
    cluster_groups: list[FactorClusterGroup] = Field(default_factory=list)
    pool_health: str = "因子不足"
    recommendations: list[str] = Field(default_factory=list)
