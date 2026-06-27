from __future__ import annotations

import pandas as pd

from app.factors.base import Factor


class Turnover20D(Factor):
    name = "turnover_20d"
    label = "20日均成交额"
    description = "20-day rolling average of daily turnover amount — 流动性代理指标"
    lookback_days = 20
    direction = "higher_better"
    category = "liquidity"
    value_format = "amount"
    interpretation = "衡量近 20 个交易日成交额水平，数值越高代表交易承载能力越好。"

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        frame = daily[["symbol", "date", "amount"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values(["symbol", "date"])
        frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
        return frame.groupby("symbol")["amount"].transform(
            lambda x: x.rolling(20, min_periods=5).mean()
        )
