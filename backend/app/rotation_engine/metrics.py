from __future__ import annotations

import numpy as np
import pandas as pd

from .config import TRADING_DAYS_PER_YEAR


def annualized_return(daily_returns: pd.Series) -> float:
    if daily_returns.empty:
        return 0.0
    cumulative = float((1 + daily_returns).prod())
    n = len(daily_returns)
    if n == 0 or cumulative <= 0:
        return -1.0
    return cumulative ** (TRADING_DAYS_PER_YEAR / n) - 1


def max_drawdown_with_dates(daily_returns: pd.Series) -> tuple[float, str, str]:
    if daily_returns.empty:
        return 0.0, "", ""
    equity = (1 + daily_returns).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1
    trough_date = dd.idxmin()
    peak_date = equity.loc[:trough_date].idxmax()
    return float(dd.min()), str(peak_date.date()), str(trough_date.date())


def max_drawdown(daily_returns: pd.Series) -> float:
    mdd, _, _ = max_drawdown_with_dates(daily_returns)
    return mdd


def sharpe_ratio(daily_returns: pd.Series) -> float:
    if daily_returns.empty or len(daily_returns) < 2 or daily_returns.std(ddof=1) == 0:
        return 0.0
    return float(
        daily_returns.mean() / daily_returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
    )


def calmar_ratio(daily_returns: pd.Series) -> float:
    mdd = max_drawdown(daily_returns)
    if mdd == 0:
        return 0.0
    return annualized_return(daily_returns) / abs(mdd)
