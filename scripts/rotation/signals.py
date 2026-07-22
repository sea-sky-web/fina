from __future__ import annotations

import numpy as np
import pandas as pd

from .config import ClassConfig, StrategyConfig, DEFAULT_CONFIG


def vectorized_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    mean = frame.mean(axis=1)
    std = frame.std(axis=1, ddof=0).replace(0, np.nan)
    z = frame.sub(mean, axis=0).div(std, axis=0)
    return z.fillna(0.0)


def vectorized_pct_rank(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rank(axis=1, pct=True).fillna(0.5)


def compute_scores(
    close: pd.DataFrame,
    symbols: list[str],
    amount: pd.DataFrame,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """原始单类评分 — 完全向后兼容."""
    return _score_core(
        close, symbols, amount,
        benchmark=config.benchmark,
        momentum_lookback_set=config.momentum_lookback_set,
        rel_strength_lookback=config.rel_strength_lookback,
    )


def compute_class_scores(
    close: pd.DataFrame,
    symbols: list[str],
    amount: pd.DataFrame,
    class_config: ClassConfig,
) -> pd.DataFrame:
    """多资产模式下的类内评分 — 使用各类自己的基准和参数."""
    return _score_core(
        close, symbols, amount,
        benchmark=class_config.benchmark,
        momentum_lookback_set=class_config.momentum_lookback_set,
        rel_strength_lookback=class_config.rel_strength_lookback,
    )


def _score_core(
    close: pd.DataFrame,
    symbols: list[str],
    amount: pd.DataFrame,
    *,
    benchmark: str,
    momentum_lookback_set: list[int],
    rel_strength_lookback: int,
) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame(index=close.index)

    mom_components = []
    for L in momentum_lookback_set:
        ret = close[symbols].pct_change(L)
        mom_components.append(vectorized_zscore(ret))
    mom_z = sum(mom_components) / len(mom_components)

    bench_ret_long = close[benchmark].pct_change(rel_strength_lookback)
    ret_long = close[symbols].pct_change(rel_strength_lookback)
    excess_long = ret_long.sub(bench_ret_long, axis=0)
    rel_rank = vectorized_pct_rank(excess_long)

    bench = close[benchmark]
    ma20 = bench.rolling(20).mean()
    ma60 = bench.rolling(60).mean()
    bear_mask = (ma20 < ma60).reindex(close.index).fillna(False)

    w_mom = pd.Series(0.55, index=close.index)
    w_rel = pd.Series(0.45, index=close.index)
    w_mom[bear_mask] = 0.35
    w_rel[bear_mask] = 0.65

    score = mom_z.mul(w_mom, axis=0) + rel_rank.mul(w_rel, axis=0)

    vol_ratio = amount[symbols].rolling(5).mean() / amount[symbols].rolling(20).mean()
    price_up = close[symbols].pct_change(5) > 0
    volume_confirmed = (vol_ratio > 1.15) & price_up
    volume_bonus = pd.DataFrame(0.0, index=close.index, columns=symbols)
    volume_bonus[volume_confirmed] = 0.3
    price_down_vol_up = (vol_ratio > 1.15) & ~price_up
    volume_bonus[price_down_vol_up] = -0.3
    volume_bonus[bear_mask] = 0.0
    score = score + volume_bonus

    score[excess_long.isna()] = np.nan
    return score
