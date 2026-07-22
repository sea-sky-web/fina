"""Layer 1: 宏观大类资产配置 — 双动量模型."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .asset_class import AssetClass, CLASS_BENCHMARK
from .config import MacroConfig


def _trend_on(prices: pd.Series, ma_short: int, ma_long: int) -> bool:
    if len(prices) < ma_long:
        return False
    return float(prices.rolling(ma_short).mean().iloc[-1]) > float(
        prices.rolling(ma_long).mean().iloc[-1]
    )


def macro_allocate(
    bench_prices: dict[AssetClass, pd.Series],
    config: MacroConfig,
    date: pd.Timestamp,
) -> dict[AssetClass, float]:
    """单次宏观配置决策.

    对每个大类做双重过滤:
      1. 绝对动量 — 自身基准 MA_short > MA_long
      2. 横截面动量 — N 日收益在所有大类中排名 > 中位数
    两者都通过 → 分配基础权重，否则 → 资金转入避险类（债券）.
    """
    sliced = {c: p.loc[:date].dropna() for c, p in bench_prices.items()}

    trend = {
        c: _trend_on(p, config.trend_ma_short, config.trend_ma_long)
        for c, p in sliced.items()
    }

    mom = {}
    for c, p in sliced.items():
        if len(p) >= config.momentum_lookback:
            mom[c] = float(p.iloc[-1] / p.iloc[-config.momentum_lookback] - 1)
        else:
            mom[c] = -np.inf
    if mom:
        median_mom = float(np.median(list(mom.values())))
    else:
        median_mom = 0.0
    xs_on = {c: mom.get(c, -np.inf) >= median_mom for c in sliced}

    weights: dict[AssetClass, float] = {}
    redirected = 0.0
    for c in sliced:
        base = config.base_weights.get(c, 0.0)
        if trend[c] and xs_on[c]:
            weights[c] = base
        else:
            weights[c] = 0.0
            redirected += base

    safe = config.safe_haven
    weights[safe] = weights.get(safe, 0.0) + redirected

    total = sum(weights.values())
    if total > 0:
        weights = {c: w / total for c, w in weights.items()}

    return weights


def run_macro_allocation(
    bench_prices: dict[AssetClass, pd.Series],
    config: MacroConfig,
    trading_dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    """在每个月末重新平衡，其余日期 forward-fill."""
    months = trading_dates.to_series().groupby(
        trading_dates.to_period("M")
    ).last()
    rebal_dates = months.tolist()

    records = []
    for rd in rebal_dates:
        w = macro_allocate(bench_prices, config, rd)
        row = {"date": rd}
        for c in AssetClass:
            if c != AssetClass.EXCLUDED:
                row[c.value] = w.get(c, 0.0)
        records.append(row)

    wdf = pd.DataFrame(records).set_index("date")
    wdf = wdf.reindex(trading_dates, method="ffill")

    for col in wdf.columns:
        wdf[col] = wdf[col].fillna(0.0)
    return wdf
