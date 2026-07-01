from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime

from pydantic import BaseModel, Field


class EtfBasic(BaseModel):
    symbol: str
    code: str
    exchange: str
    name: str
    theme: str = "其他"
    full_name: str | None = None
    index_code: str | None = None
    index_name: str | None = None
    manager: str | None = None
    list_date: dt_date | None = None
    latest_price: float | None = None
    iopv: float | None = None
    premium_discount_rate: float | None = None
    pct_chg: float | None = None
    change: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    pre_close: float | None = None
    amplitude: float | None = None
    volume: float | None = None
    amount: float | None = None
    turnover_rate: float | None = None
    volume_ratio: float | None = None
    latest_share: float | None = None
    circulating_market_value: float | None = None
    total_market_value: float | None = None
    spot_date: dt_date | None = None
    quote_updated_at: datetime | None = None
    status: str | None = None
    provider: str = "unknown"
    source_endpoint: str | None = None
    updated_at: datetime | None = None


class EtfDailyBar(BaseModel):
    symbol: str
    date: dt_date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    pre_close: float | None = None
    change: float | None = None
    pct_chg: float | None = None
    volume: float | None = None
    amount: float | None = None
    amplitude: float | None = None
    turnover_rate: float | None = None
    factor: float = 1.0
    provider: str = "unknown"
    source_endpoint: str | None = None
    updated_at: datetime | None = None


class DataStatus(BaseModel):
    provider: str
    dataset: str
    last_success_at: datetime | None = None
    last_trade_date: dt_date | None = None
    rows: int = 0
    status: str = Field(pattern="^(ok|stale|empty|error)$")
    message: str


class DataSourceAudit(BaseModel):
    generated_at: datetime
    ok: bool
    status: str = Field(pattern="^(ok|warning|error)$")
    provider: str = "unknown"
    manifest_status: str | None = None
    collected_at: datetime | None = None
    spot_source: str | None = None
    selected_rows: int = 0
    basic_rows: int = 0
    daily_rows: int = 0
    latest_trade_date: dt_date | None = None
    symbols_total: int = 0
    symbols_with_daily: int = 0
    daily_missing_symbols: list[str] = Field(default_factory=list)
    source_endpoints: list[str] = Field(default_factory=list)
    cached_sources: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RefreshResult(BaseModel):
    ok: bool
    message: str
    provider: str = "akshare"
    selected_rows: int = 0
    daily_rows: int = 0
    factor_rows: int = 0
    factor_latest_date: dt_date | None = None
    refreshed_at: datetime | None = None
    failures: list[dict[str, str]] = Field(default_factory=list)


class RotationScoreModel(BaseModel):
    symbol: str
    name: str
    theme: str
    etf_type: str
    date: dt_date
    total_score: float
    boom_score: float
    momentum_score: float
    valuation_score: float
    structure_score: float
    liquidity_score: float
    risk_score: float
    boom_status: str
    boom_source: str = "data"
    valuation_percentile: float
    state: str
    action: str
    returns: dict[str, float | None] = Field(default_factory=dict)
    risk_notes: list[str] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    input_notes: str = ""


class RotationReportModel(BaseModel):
    radar_date: dt_date | None = None
    rankings: list[RotationScoreModel] = Field(default_factory=list)
    pools: dict[str, list[str]] = Field(default_factory=dict)
    data_notes: list[str] = Field(default_factory=list)


class FactorScore(BaseModel):
    symbol: str
    name: str
    theme: str
    date: dt_date
    factor_name: str
    factor_value: float
    rank: int
    percentile: float
    lookback_days: int = 0
    provider: str = "local"
    updated_at: datetime | None = None


class FactorHistoryPoint(BaseModel):
    date: dt_date
    factor_value: float
    rank: int
    percentile: float


class FactorDistribution(BaseModel):
    count: int = 0
    missing_count: int = 0
    min: float | None = None
    p25: float | None = None
    median: float | None = None
    p75: float | None = None
    max: float | None = None
    mean: float | None = None


class FactorForwardReturn(BaseModel):
    horizon: int
    sample_count: int = 0
    top_mean: float | None = None
    bottom_mean: float | None = None
    spread: float | None = None
    data_notes: list[str] = Field(default_factory=list)


class FactorStability(BaseModel):
    lookback_dates: int = 0
    average_rank_change: float | None = None
    label: str = "样本不足"
    data_notes: list[str] = Field(default_factory=list)


class FactorDiagnostics(BaseModel):
    factor_name: str
    date: dt_date | None = None
    definition: dict[str, object]
    distribution: FactorDistribution
    top: list[FactorScore] = Field(default_factory=list)
    bottom: list[FactorScore] = Field(default_factory=list)
    forward_return: FactorForwardReturn
    stability: FactorStability
    data_notes: list[str] = Field(default_factory=list)


class SignalComponent(BaseModel):
    factor_name: str
    label: str
    category: str
    direction: str
    value_format: str
    factor_value: float
    rank: int
    percentile: float
    weight: float
    contribution: float
    interpretation: str


class SignalExplanation(BaseModel):
    positive_drivers: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)
    data_notes: list[str] = Field(default_factory=list)


class MarketRegimeSnapshot(BaseModel):
    label: str = "neutral"
    label_zh: str = "中性"
    date: dt_date | None = None
    target_exposure: float = 0.75
    trend_score: float | None = None
    volatility_annualized: float | None = None
    drawdown: float | None = None
    source: str = "universe_equal_weight"
    data_notes: list[str] = Field(default_factory=list)


class ResearchSignal(BaseModel):
    symbol: str
    name: str
    theme: str
    date: dt_date
    research_score: float
    priority: str
    components: list[SignalComponent] = Field(default_factory=list)
    explanation: SignalExplanation
    market_regime: MarketRegimeSnapshot | None = None
    target_exposure: float | None = None
    provider: str = "local"
    updated_at: datetime | None = None


class BacktestConfig(BaseModel):
    start: dt_date | None = None
    end: dt_date | None = None
    top_n: int = 10
    rebalance: str = "monthly"
    cost_bps: float = 5.0
    benchmark: str = "510300.SH"


class BacktestMetrics(BaseModel):
    cumulative_return: float | None = None
    annualized_return: float | None = None
    annualized_volatility: float | None = None
    max_drawdown: float | None = None
    sharpe_like: float | None = None
    win_rate_daily: float | None = None
    average_turnover: float | None = None
    rebalance_count: int = 0
    final_equity: float | None = None


class BacktestEquityPoint(BaseModel):
    date: dt_date
    equity: float
    daily_return: float | None = None


class BacktestHolding(BaseModel):
    symbol: str
    name: str
    theme: str
    research_score: float
    weight: float


class BacktestHoldingSnapshot(BaseModel):
    rebalance_date: dt_date
    effective_date: dt_date | None = None
    holdings: list[BacktestHolding] = Field(default_factory=list)
    turnover: float = 0.0
    cost: float = 0.0
    regime: MarketRegimeSnapshot | None = None
    target_exposure: float = 1.0
    realized_exposure: float = 1.0
    cash_weight: float = 0.0
    risk_notes: list[str] = Field(default_factory=list)


class BacktestBenchmark(BaseModel):
    key: str
    label: str
    symbol: str | None = None
    metrics: BacktestMetrics
    equity_curve: list[BacktestEquityPoint] = Field(default_factory=list)


class BacktestDataNote(BaseModel):
    severity: str = "info"
    message: str


class BacktestRiskSummary(BaseModel):
    average_target_exposure: float | None = None
    average_realized_exposure: float | None = None
    average_cash_weight: float | None = None
    risk_off_rebalance_count: int = 0
    constrained_rebalance_count: int = 0
    data_notes: list[str] = Field(default_factory=list)


class BacktestResult(BaseModel):
    config: BacktestConfig
    metrics: BacktestMetrics
    equity_curve: list[BacktestEquityPoint] = Field(default_factory=list)
    benchmarks: list[BacktestBenchmark] = Field(default_factory=list)
    holdings: list[BacktestHoldingSnapshot] = Field(default_factory=list)
    risk_summary: BacktestRiskSummary | None = None
    data_notes: list[BacktestDataNote] = Field(default_factory=list)


class SignalSnapshotResult(BaseModel):
    ok: bool
    date: str | None = None
    rows: int = 0
    message: str = ""


class SignalPerformanceModel(BaseModel):
    snapshot_date: dt_date
    horizon_days: int
    top_mean_return: float = 0.0
    benchmark_return: float = 0.0
    excess_return: float = 0.0
    hit_rate: float = 0.0
    score_return_corr: float | None = None
    top_symbols: list[str] = Field(default_factory=list)
    data_notes: list[str] = Field(default_factory=list)


class MonitoringCheck(BaseModel):
    key: str
    label: str
    status: str = Field(pattern="^(ok|watch|alert|missing)$")
    value: str = ""
    detail: str = ""


class MonitoringReport(BaseModel):
    generated_at: datetime
    market_regime: MarketRegimeSnapshot | None = None
    checks: list[MonitoringCheck] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    data_notes: list[str] = Field(default_factory=list)
