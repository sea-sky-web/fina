from __future__ import annotations

import pandas as pd

from .config import DATA_PATH, StrategyConfig, DEFAULT_CONFIG


def load_data(
    config: StrategyConfig = DEFAULT_CONFIG,
    path=None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    path = path or DATA_PATH
    raw = pd.read_parquet(path)
    raw["date"] = pd.to_datetime(raw["date"])
    close = raw.pivot(index="date", columns="symbol", values="close").sort_index()
    amount = raw.pivot(index="date", columns="symbol", values="amount").sort_index()
    close = close.ffill(limit=2)
    symbols = [c for c in close.columns if c != config.benchmark]
    return close, amount, symbols


def liquidity_filter(
    amount: pd.DataFrame,
    symbols: list[str],
    config: StrategyConfig = DEFAULT_CONFIG,
    cutoff_date: pd.Timestamp | None = None,
) -> list[str]:
    amt = amount[symbols]
    if cutoff_date is not None:
        amt = amt.loc[:cutoff_date]
    avg_amount = amt.mean()
    kept = [s for s in symbols if avg_amount.get(s, 0) >= config.min_avg_amount]
    dropped = sorted(set(symbols) - set(kept))
    if dropped:
        print(f"[liquidity_filter] dropped {len(dropped)} low-liquidity symbols: {dropped}")
    return kept


def restrict_to_common_history(
    close: pd.DataFrame,
    symbols: list[str],
    config: StrategyConfig = DEFAULT_CONFIG,
) -> pd.DatetimeIndex:
    valid = close[symbols + [config.benchmark]].dropna(how="any")
    return valid.index
