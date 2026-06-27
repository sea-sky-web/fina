from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from app.risk.regime import MarketRegime


@dataclass(frozen=True)
class RiskConfig:
    max_symbol_weight: float = 0.30
    max_theme_weight: float = 0.55
    max_pairwise_correlation: float = 0.90
    max_correlation_cluster_weight: float = 0.65
    correlation_lookback_days: int = 60


@dataclass(frozen=True)
class RiskAdjustedPortfolio:
    weights: dict[str, float]
    cash_weight: float
    target_exposure: float
    realized_exposure: float
    notes: list[str] = field(default_factory=list)


def _cap_symbol_weights(
    weights: dict[str, float],
    config: RiskConfig,
) -> tuple[dict[str, float], list[str]]:
    capped: dict[str, float] = {}
    notes: list[str] = []
    for symbol, weight in weights.items():
        next_weight = min(weight, config.max_symbol_weight)
        if next_weight < weight:
            notes.append(f"{symbol} 单只权重超过上限，已压降至 {config.max_symbol_weight:.0%}。")
        capped[symbol] = next_weight
    return capped, notes


def _cap_theme_weights(
    weights: dict[str, float],
    themes: dict[str, str],
    config: RiskConfig,
) -> tuple[dict[str, float], list[str]]:
    adjusted = weights.copy()
    notes: list[str] = []
    theme_totals: dict[str, float] = {}
    for symbol, weight in adjusted.items():
        theme = themes.get(symbol, "其他")
        theme_totals[theme] = theme_totals.get(theme, 0.0) + weight

    for theme, total in theme_totals.items():
        if total <= config.max_theme_weight or total <= 0:
            continue
        scale = config.max_theme_weight / total
        for symbol in [item for item in adjusted if themes.get(item, "其他") == theme]:
            adjusted[symbol] *= scale
        notes.append(f"{theme} 主题合计权重超过上限，已按比例压降。")
    return adjusted, notes


def _recent_correlations(
    daily: pd.DataFrame,
    symbols: list[str],
    as_of: date,
    lookback_days: int,
) -> pd.DataFrame:
    if daily.empty or not {"symbol", "date", "close"}.issubset(daily.columns) or len(symbols) < 2:
        return pd.DataFrame()
    frame = daily[daily["symbol"].isin(symbols)].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame[frame["date"] <= as_of]
    if frame.empty:
        return pd.DataFrame()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    prices = frame.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
    returns = prices.sort_index().pct_change(fill_method=None).tail(lookback_days)
    return returns.corr()


def _correlation_clusters(corr: pd.DataFrame, threshold: float) -> list[set[str]]:
    if corr.empty:
        return []
    symbols = list(corr.columns)
    graph = {symbol: set() for symbol in symbols}
    for left_index, left in enumerate(symbols):
        for right in symbols[left_index + 1 :]:
            value = corr.loc[left, right]
            if pd.notna(value) and abs(float(value)) >= threshold:
                graph[left].add(right)
                graph[right].add(left)

    visited: set[str] = set()
    clusters: list[set[str]] = []
    for symbol in symbols:
        if symbol in visited:
            continue
        stack = [symbol]
        cluster: set[str] = set()
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            cluster.add(current)
            stack.extend(graph[current] - visited)
        if len(cluster) > 1:
            clusters.append(cluster)
    return clusters


def _cap_correlation_clusters(
    weights: dict[str, float],
    daily: pd.DataFrame,
    as_of: date,
    config: RiskConfig,
) -> tuple[dict[str, float], list[str]]:
    adjusted = weights.copy()
    corr = _recent_correlations(
        daily,
        list(adjusted),
        as_of,
        config.correlation_lookback_days,
    )
    notes: list[str] = []
    for cluster in _correlation_clusters(corr, config.max_pairwise_correlation):
        cluster_weight = sum(adjusted.get(symbol, 0.0) for symbol in cluster)
        if cluster_weight <= config.max_correlation_cluster_weight or cluster_weight <= 0:
            continue
        scale = config.max_correlation_cluster_weight / cluster_weight
        for symbol in cluster:
            adjusted[symbol] *= scale
        notes.append(
            "高相关 ETF 簇合计权重超过上限，已降低该簇暴露。"
        )
    return adjusted, notes


def build_risk_adjusted_portfolio(
    symbols: list[str],
    scores: dict[str, float],
    daily: pd.DataFrame,
    as_of: date,
    themes: dict[str, str],
    regime: MarketRegime,
    config: RiskConfig | None = None,
) -> RiskAdjustedPortfolio:
    cfg = config or RiskConfig()
    ordered_symbols = [symbol for symbol in symbols if symbol in scores]
    if not ordered_symbols:
        return RiskAdjustedPortfolio(
            weights={},
            cash_weight=1.0,
            target_exposure=regime.target_exposure,
            realized_exposure=0.0,
            notes=["无可配置标的，组合保持现金。"],
        )

    equal_weight = regime.target_exposure / len(ordered_symbols)
    weights = {symbol: equal_weight for symbol in ordered_symbols}
    notes = [
        f"市场状态为{regime.label_zh}，目标风险暴露 {regime.target_exposure:.0%}。",
    ]

    for adjuster in [
        lambda current: _cap_symbol_weights(current, cfg),
        lambda current: _cap_theme_weights(current, themes, cfg),
        lambda current: _cap_correlation_clusters(current, daily, as_of, cfg),
    ]:
        weights, new_notes = adjuster(weights)
        notes.extend(new_notes)

    weights = {
        symbol: round(weight, 10)
        for symbol, weight in weights.items()
        if weight > 0
    }
    realized_exposure = min(sum(weights.values()), 1.0)
    cash_weight = max(0.0, 1.0 - realized_exposure)
    if cash_weight > 0.01:
        notes.append(f"约 {cash_weight:.0%} 资金因风险约束保留为现金/低风险仓位。")

    return RiskAdjustedPortfolio(
        weights=weights,
        cash_weight=cash_weight,
        target_exposure=regime.target_exposure,
        realized_exposure=realized_exposure,
        notes=notes,
    )
