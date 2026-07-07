from __future__ import annotations

import pandas as pd

from app.factors.base import Factor


class Reversal5D(Factor):
    name = "reversal_5d"
    label = "5日短期反转"
    description = "-1 * (close_today / close_5d_ago - 1)"
    lookback_days = 5
    direction = "higher_better"
    category = "reversal"
    value_format = "percent"
    interpretation = "过去5日涨幅越大得分越低，捕捉短期均值回归。"

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        frame = daily[["symbol", "date", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values(["symbol", "date"])
        return -1 * frame.groupby("symbol")["close"].pct_change(periods=5)
