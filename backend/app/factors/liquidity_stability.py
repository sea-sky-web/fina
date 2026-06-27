from __future__ import annotations

import numpy as np
import pandas as pd

from app.factors.base import Factor


class LiquidityStability20D(Factor):
    name = "liquidity_stability_20d"
    label = "20日流动性稳定性"
    description = (
        "20-day average turnover amount divided by turnover standard deviation — 成交额稳定性"
    )
    lookback_days = 20
    direction = "higher_better"
    category = "liquidity"
    value_format = "ratio"
    interpretation = "衡量近 20 日成交额是否稳定，数值越高代表成交额更连续、更不依赖单日放量。"

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        frame = daily[["symbol", "date", "amount"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
        frame = frame.sort_values(["symbol", "date"])
        rolling_mean = frame.groupby("symbol")["amount"].transform(
            lambda x: x.rolling(20, min_periods=5).mean()
        )
        rolling_std = frame.groupby("symbol")["amount"].transform(
            lambda x: x.rolling(20, min_periods=5).std()
        )
        return rolling_mean / rolling_std.replace(0, np.nan)
