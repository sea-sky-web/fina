from __future__ import annotations

import numpy as np
import pandas as pd

from app.factors.base import Factor


class RiskAdjustedReturn60D(Factor):
    name = "risk_adjusted_return_60d"
    label = "60日风险调整收益"
    description = "60-day momentum divided by 30-day annualized volatility — 趋势收益相对波动的效率"
    lookback_days = 60
    direction = "higher_better"
    category = "return"
    value_format = "ratio"
    interpretation = "衡量近 60 日收益相对短期波动的效率，数值越高代表单位波动带来的趋势收益越好。"

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        frame = daily[["symbol", "date", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.sort_values(["symbol", "date"])
        frame["momentum"] = frame.groupby("symbol")["close"].pct_change(periods=60)
        frame["log_ret"] = frame.groupby("symbol")["close"].transform(
            lambda x: np.log(x / x.shift(1))
        )
        frame["volatility"] = frame.groupby("symbol")["log_ret"].transform(
            lambda x: x.rolling(30, min_periods=10).std() * np.sqrt(252)
        )
        return frame["momentum"] / frame["volatility"].replace(0, np.nan)
