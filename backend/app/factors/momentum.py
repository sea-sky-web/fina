from __future__ import annotations

import pandas as pd

from app.factors.base import Factor


class Momentum60D(Factor):
    name = "momentum_60d"
    label = "60日动量"
    description = "close_today / close_60_trading_days_ago - 1"
    lookback_days = 60
    direction = "higher_better"
    category = "return"
    value_format = "percent"
    interpretation = "衡量近 60 个交易日价格强弱，数值越高代表近期相对表现越强。"

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        frame = daily[["symbol", "date", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values(["symbol", "date"])
        return frame.groupby("symbol")["close"].pct_change(periods=60)
