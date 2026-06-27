from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import sqrt

import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class MarketRegime:
    label: str
    date: date | None
    target_exposure: float
    trend_score: float | None = None
    volatility_annualized: float | None = None
    drawdown: float | None = None
    source: str = "universe_equal_weight"
    data_notes: list[str] = field(default_factory=list)

    @property
    def label_zh(self) -> str:
        return {
            "risk_on": "风险偏好",
            "neutral": "中性",
            "risk_off": "防御",
        }.get(self.label, self.label)


def _clean_daily(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty or not {"symbol", "date", "close"}.issubset(daily.columns):
        return pd.DataFrame(columns=["symbol", "date", "close"])
    frame = daily[["symbol", "date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["symbol", "date", "close"]).sort_values(["symbol", "date"])


def _market_series(
    daily: pd.DataFrame,
    as_of: date | None,
    benchmark: str,
) -> tuple[pd.Series, str, list[str]]:
    frame = _clean_daily(daily)
    if frame.empty:
        return pd.Series(dtype="float64"), "none", ["缺少可用日线数据，市场状态按中性处理。"]
    if as_of is not None:
        frame = frame[frame["date"] <= as_of]
    if frame.empty:
        return (
            pd.Series(dtype="float64"),
            "none",
            ["目标日期之前缺少日线数据，市场状态按中性处理。"],
        )

    prices = frame.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
    prices = prices.sort_index()
    benchmark_prices = prices.get(benchmark)
    if benchmark_prices is not None and benchmark_prices.dropna().shape[0] >= 60:
        return benchmark_prices.dropna(), benchmark, [f"市场状态参考 {benchmark}。"]

    returns = prices.pct_change(fill_method=None).mean(axis=1, skipna=True).fillna(0.0)
    return (1 + returns).cumprod(), "universe_equal_weight", ["市场状态参考 ETF 池等权走势。"]


def detect_market_regime(
    daily: pd.DataFrame,
    as_of: date | None = None,
    *,
    benchmark: str = "510300.SH",
) -> MarketRegime:
    """Classify a lightweight market regime from point-in-time prices.

    The rule intentionally uses common, transparent inputs: trend versus a medium-term moving
    average, recent realized volatility, and drawdown from the recent high.
    """
    series, source, notes = _market_series(daily, as_of, benchmark)
    if series.empty or len(series) < 60:
        return MarketRegime(
            label="neutral",
            date=series.index[-1] if not series.empty else as_of,
            target_exposure=0.75,
            source=source,
            data_notes=[*notes, "市场状态样本不足 60 个交易日，默认中性暴露。"],
        )

    returns = series.pct_change(fill_method=None).dropna()
    short_ma = float(series.tail(20).mean())
    long_ma = float(series.tail(60).mean())
    latest = float(series.iloc[-1])
    trend_score = short_ma / long_ma - 1 if long_ma else 0.0
    recent_high = float(series.tail(120).max())
    drawdown = latest / recent_high - 1 if recent_high else 0.0
    volatility = float(returns.tail(20).std(ddof=0) * sqrt(TRADING_DAYS_PER_YEAR))

    if drawdown <= -0.12 or trend_score < -0.02 or volatility >= 0.35:
        label = "risk_off"
        exposure = 0.45
        notes.append("趋势、波动或回撤触发防御状态，组合目标暴露降低。")
    elif trend_score >= 0.02 and drawdown > -0.08 and volatility < 0.28:
        label = "risk_on"
        exposure = 0.95
        notes.append("趋势向上且波动/回撤可控，组合保持较高目标暴露。")
    else:
        label = "neutral"
        exposure = 0.75
        notes.append("趋势或风险指标未形成强信号，组合使用中性目标暴露。")

    return MarketRegime(
        label=label,
        date=series.index[-1],
        target_exposure=exposure,
        trend_score=float(trend_score),
        volatility_annualized=volatility,
        drawdown=float(drawdown),
        source=source,
        data_notes=notes,
    )
