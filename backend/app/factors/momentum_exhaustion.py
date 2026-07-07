from __future__ import annotations

import pandas as pd

from app.factors.base import Factor


class MomentumExhaustion(Factor):
    name = "momentum_exhaustion"
    label = "动量衰竭"
    description = "近5日收益占60日收益的比重，衡量上涨是否在减速"
    lookback_days = 60
    direction = "higher_better"
    category = "reversal"
    value_format = "ratio"
    interpretation = "比率高=动量仍在加速；比率低或为负=上涨趋势可能尾声。"

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        frame = daily[["symbol", "date", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values(["symbol", "date"])
        ret_5d = frame.groupby("symbol")["close"].pct_change(periods=5)
        ret_60d = frame.groupby("symbol")["close"].pct_change(periods=60)
        safe_denom = ret_60d.abs().clip(lower=0.03)
        result = ret_5d / safe_denom
        return result.clip(lower=-5, upper=5)
