from __future__ import annotations

import pandas as pd

from app.factors.base import Factor


class DeviationRate60D(Factor):
    name = "deviation_rate_60d"
    label = "60日均线乖离率"
    description = "-1 * (close / MA60 - 1)，偏离越大得分越低"
    lookback_days = 60
    direction = "higher_better"
    category = "crowding"
    value_format = "percent"
    interpretation = "价格远高于60日均线=超买=得分低；接近或低于=安全=得分高。"

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        frame = daily[["symbol", "date", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values(["symbol", "date"])
        ma60 = frame.groupby("symbol")["close"].transform(
            lambda s: s.rolling(60, min_periods=40).mean()
        )
        safe_ma = ma60.replace(0, float("nan"))
        return -1 * (frame["close"] / safe_ma - 1)
