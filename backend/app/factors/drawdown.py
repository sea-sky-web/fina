from __future__ import annotations

import pandas as pd

from app.factors.base import Factor


class MaxDrawdown60D(Factor):
    name = "max_drawdown_60d"
    label = "60日最大回撤"
    description = "max drawdown over a 60-day rolling window — 尾部风险度量（值为负，越小回撤越大）"
    lookback_days = 60
    direction = "higher_better"
    category = "risk"
    value_format = "percent"
    interpretation = "衡量近 60 个交易日最大回撤，越接近 0 代表近期回撤压力越小。"

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        frame = daily[["symbol", "date", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values(["symbol", "date"])
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")

        def _rolling_max_drawdown(series: pd.Series) -> pd.Series:
            running_max = series.rolling(60, min_periods=10).max()
            drawdown = (series - running_max) / running_max
            return drawdown.rolling(60, min_periods=10).min()

        return frame.groupby("symbol")["close"].transform(_rolling_max_drawdown)
