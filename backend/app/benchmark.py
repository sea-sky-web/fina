"""实时对照基准 — 每次运行都查当前货基收益率，不写死历史数值。

天弘余额宝(000198)是支付宝独有渠道产品，AKShare 的东方财富货基排行接口不覆盖它。
用全市场货币基金七日年化收益率的中位数替代，更能代表"随手放着不动的现金"的
普遍收益水平，不依赖单一产品的特殊费率结构。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class CashBenchmark:
    annualized_pct: float
    sample_size: int
    as_of: str
    note: str


def fetch_cash_benchmark() -> CashBenchmark:
    import akshare as ak

    frame = ak.fund_money_rank_em()
    if frame is None or frame.empty:
        raise ValueError("AKShare 返回空的货币基金排行数据")
    yields = pd.to_numeric(frame["年化收益率7日"], errors="coerce").dropna()
    as_of = str(frame["日期"].iloc[0]) if "日期" in frame.columns and not frame.empty else ""
    return CashBenchmark(
        annualized_pct=float(yields.median()),
        sample_size=int(yields.shape[0]),
        as_of=as_of,
        note="全市场货币基金七日年化收益率中位数(天弘余额宝未被该数据源覆盖，用同类产品中位数替代)",
    )
