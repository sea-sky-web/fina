from __future__ import annotations

import pandas as pd

from app.factors.base import Factor


class TrendStrength20To60D(Factor):
    name = "trend_strength_20_60d"
    label = "20/60日趋势强度"
    description = "20-day moving average divided by 60-day moving average - 1 — 中短期趋势确认"
    lookback_days = 60
    direction = "higher_better"
    category = "trend"
    value_format = "percent"
    interpretation = "衡量 20 日均线相对 60 日均线的位置，数值越高代表中短期趋势越强。"

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        frame = daily[["symbol", "date", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.sort_values(["symbol", "date"])
        ma20 = frame.groupby("symbol")["close"].transform(
            lambda x: x.rolling(20, min_periods=10).mean()
        )
        ma60 = frame.groupby("symbol")["close"].transform(
            lambda x: x.rolling(60, min_periods=30).mean()
        )
        return ma20 / ma60 - 1
