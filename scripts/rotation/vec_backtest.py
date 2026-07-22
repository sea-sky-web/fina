"""Layer 2 验证: 向量化全量回测 — 独立于 engine.py 实现."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StrategyConfig, DEFAULT_CONFIG


def vec_simulate(
    score_full: pd.DataFrame,
    close: pd.DataFrame,
    symbols: list[str],
    k_schedule: list[dict],
    config: StrategyConfig = DEFAULT_CONFIG,
) -> pd.Series:
    """纯向量化回测.

    k_schedule: [{test_start, test_end, best_K, step_days}, ...]
    不实现止损/熔断/再入场, 只验证选股+权重+成本+牛熊缩放的基础逻辑.
    """
    bench = close[config.benchmark]
    bench_ma10 = bench.rolling(10).mean()
    bench_ma30 = bench.rolling(30).mean()
    bear_mask = bench_ma10 < bench_ma30

    all_daily_ret = []

    for window in k_schedule:
        t_start = pd.Timestamp(window["test_start"])
        t_end = pd.Timestamp(window["test_end"])
        K = window["best_K"]
        step = window.get("step_days", config.step_trading_days)

        dates = close.index[(close.index >= t_start) & (close.index <= t_end)]
        dates = dates[:step]
        if dates.empty:
            continue

        scores = score_full.reindex(dates)[symbols]
        prices = close.reindex(dates)[symbols]
        returns = prices.pct_change()

        prev_weights = pd.Series(0.0, index=symbols)

        for d in dates:
            row = scores.loc[d].dropna()
            positive = row[row > 0].sort_values(ascending=False)
            chosen = list(positive.head(K).index)

            weights = pd.Series(0.0, index=symbols)
            if chosen:
                w = min(1.0 / len(chosen), config.max_symbol_weight)
                for s in chosen:
                    weights[s] = w

            is_bear = bool(bear_mask.get(d, False))
            scale = config.bear_scale if is_bear else config.bull_boost
            weights = weights * scale

            turnover = float((weights - prev_weights).abs().sum())
            cost = turnover * config.cost_rate_one_side

            day_ret = returns.loc[d].reindex(symbols).fillna(0.0) if d != dates[0] else pd.Series(0.0, index=symbols)
            gross = float((prev_weights * day_ret).sum())
            net = gross - cost

            prev_weights = weights
            all_daily_ret.append({"date": d, "net_return": net})

    if not all_daily_ret:
        return pd.Series(dtype=float)

    result = pd.DataFrame(all_daily_ret).set_index("date")["net_return"]
    result = result[~result.index.duplicated(keep="first")]
    return result.sort_index()
