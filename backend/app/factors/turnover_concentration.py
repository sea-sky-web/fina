from __future__ import annotations

import pandas as pd

from app.factors.base import Factor


class TurnoverConcentration(Factor):
    name = "turnover_concentration"
    label = "成交额拥挤度"
    description = "同主题ETF成交额占比的滚动1年百分位取反"
    lookback_days = 252
    direction = "higher_better"
    category = "crowding"
    value_format = "score"
    interpretation = "成交额占比越高=越拥挤=得分越低；不拥挤=得分高。"

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        frame = daily[["symbol", "date", "amount"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values(["symbol", "date"])
        if frame["amount"].isna().all():
            return pd.Series(float("nan"), index=frame.index)

        market_daily_amount = frame.groupby("date")["amount"].transform("sum")
        safe_market = market_daily_amount.replace(0, float("nan"))
        frame["share"] = frame["amount"] / safe_market

        share_20d = frame.groupby("symbol")["share"].transform(
            lambda s: s.rolling(20, min_periods=10).mean()
        )

        pct = frame.groupby("symbol")["share"].transform(
            lambda s: s.rolling(252, min_periods=60).apply(
                lambda w: (w.iloc[-1] <= w).sum() / len(w) * 100
                if len(w) >= 60
                else float("nan"),
                raw=False,
            )
        )
        return 100 - pct
