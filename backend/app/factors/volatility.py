from __future__ import annotations

import numpy as np
import pandas as pd

from app.factors.base import Factor


class Volatility30D(Factor):
    name = "volatility_30d"
    label = "30日波动率"
    description = "std(log_return) * sqrt(252), 30-day rolling window — 年化历史波动率"
    lookback_days = 30
    direction = "lower_better"
    category = "risk"
    value_format = "percent"
    interpretation = "衡量近 30 个交易日价格波动水平，数值越低代表短期波动风险越温和。"

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        frame = daily[["symbol", "date", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values(["symbol", "date"])
        frame["log_ret"] = frame.groupby("symbol")["close"].transform(
            lambda x: np.log(x / x.shift(1))
        )
        return frame.groupby("symbol")["log_ret"].transform(
            lambda x: x.rolling(30, min_periods=10).std() * np.sqrt(252)
        )
