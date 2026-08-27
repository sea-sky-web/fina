"""v1 规则：20日动量排名 + 20日均线趋势确认 + 流动性门槛。

有意保持这三层不再往上叠加(不做双周期z-score、不做相对强弱、不做牛熊regime切换、
不做量能加成) —— 这些是验证有效后再考虑的 v2 增强项，见 docs/STRATEGY_REVIEW.md。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.classify import infer_etf_theme, is_sector_or_theme

MOMENTUM_LOOKBACK_DAYS = 20
TREND_MA_DAYS = 20
LIQUIDITY_LOOKBACK_DAYS = 20
MIN_AVG_AMOUNT = 5.0e7  # 近20日日均成交额门槛(元)，防止选到止损时卖不掉的品种
CANDIDATE_POOL_SIZE = 50  # 按当日成交额截断，避免对全市场逐个拉历史日线


@dataclass(frozen=True)
class SymbolMetrics:
    symbol: str
    name: str
    theme: str
    latest_close: float
    momentum_20d: float | None
    ma20: float | None
    trend_ok: bool
    avg_amount_20d: float | None
    liquidity_ok: bool

    @property
    def eligible(self) -> bool:
        return self.trend_ok and self.liquidity_ok and self.momentum_20d is not None


def filter_universe(spot: pd.DataFrame) -> pd.DataFrame:
    """全市场现价快照 -> 行业/主题ETF -> 按当日成交额降序截断候选池。"""
    mask = spot["name"].apply(lambda n: is_sector_or_theme(n))
    filtered = spot[mask].copy()
    return filtered.sort_values("amount", ascending=False).head(CANDIDATE_POOL_SIZE)


def compute_symbol_metrics(symbol: str, name: str, daily: pd.DataFrame) -> SymbolMetrics | None:
    """daily 至少要覆盖 TREND_MA_DAYS+MOMENTUM_LOOKBACK_DAYS 个交易日才有意义。"""
    daily = daily.sort_values("date")
    close = pd.to_numeric(daily["close"], errors="coerce").dropna()
    amount = pd.to_numeric(daily["amount"], errors="coerce").dropna()
    if len(close) < TREND_MA_DAYS + 1:
        return None

    latest_close = float(close.iloc[-1])
    momentum_20d = (
        float(close.iloc[-1] / close.iloc[-1 - MOMENTUM_LOOKBACK_DAYS] - 1)
        if len(close) > MOMENTUM_LOOKBACK_DAYS
        else None
    )
    ma20 = float(close.tail(TREND_MA_DAYS).mean())
    trend_ok = latest_close > ma20
    avg_amount_20d = float(amount.tail(LIQUIDITY_LOOKBACK_DAYS).mean()) if not amount.empty else None
    liquidity_ok = avg_amount_20d is not None and avg_amount_20d >= MIN_AVG_AMOUNT

    return SymbolMetrics(
        symbol=symbol,
        name=name,
        theme=infer_etf_theme(name),
        latest_close=latest_close,
        momentum_20d=momentum_20d,
        ma20=ma20,
        trend_ok=trend_ok,
        avg_amount_20d=avg_amount_20d,
        liquidity_ok=liquidity_ok,
    )


def rank_candidates(metrics: list[SymbolMetrics]) -> list[SymbolMetrics]:
    """只保留同时满足趋势确认和流动性门槛的标的，按20日动量从高到低排序。

    同一主题(比如同是"黄金股ETF"的不同基金公司产品)只保留动量最高的一只——
    否则3个持仓可能挤在同一个真实风险暴露上，没有真正分散。
    """
    eligible = [m for m in metrics if m.eligible]
    ranked = sorted(eligible, key=lambda m: m.momentum_20d, reverse=True)
    seen_themes: set[str] = set()
    deduped: list[SymbolMetrics] = []
    for m in ranked:
        if m.theme in seen_themes:
            continue
        seen_themes.add(m.theme)
        deduped.append(m)
    return deduped
