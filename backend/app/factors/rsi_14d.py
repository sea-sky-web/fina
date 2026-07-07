from __future__ import annotations

import pandas as pd

from app.factors.base import Factor


class RSI14D(Factor):
    name = "rsi_14d"
    label = "14日RSI反转"
    description = "100 - RSI(14)，超买时得分低，超卖时得分高"
    lookback_days = 14
    direction = "higher_better"
    category = "reversal"
    value_format = "score"
    interpretation = "RSI越高=越超买=得分越低；RSI越低=越超卖=得分越高。"

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        frame = daily[["symbol", "date", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values(["symbol", "date"])

        delta = frame.groupby("symbol")["close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)

        avg_gain = gain.groupby(frame["symbol"]).transform(
            lambda s: s.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        )
        avg_loss = loss.groupby(frame["symbol"]).transform(
            lambda s: s.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        )

        rs = avg_gain / avg_loss.replace(0, float("nan"))
        rsi = 100 - 100 / (1 + rs)
        return 100 - rsi
