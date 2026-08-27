"""本地持仓状态 + 买卖决策。

这里存的是用户自己的交易记录(买了什么、什么价、什么时候)，不是市场数据缓存——
不属于"不落盘"的范围，止损和换手判断都要靠它才能算。
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from app.signal_rule import SymbolMetrics

STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "portfolio" / "live_state.json"

TARGET_HOLDINGS = 3
STOP_LOSS_PCT = 0.16
COST_PER_TRADE = 5.0  # 元/笔(买或卖各一笔)，3万本金分3份每份约1万，佣金基本按最低档收
# 换仓所需的最小动量分差：既要盖过双边手续费(相对1万本金约0.1%，几乎可忽略)，
# 也要盖过噪音——不然会在两个分数接近的标的之间来回抖动，这个 2% 缓冲主要是为了降噪。
MIN_SCORE_EDGE = 0.02


@dataclass
class Holding:
    symbol: str
    name: str
    entry_price: float
    entry_date: str


@dataclass
class PortfolioState:
    holdings: list[Holding] = field(default_factory=list)
    last_run_date: str | None = None


@dataclass
class Decision:
    action: str  # "卖出" | "买入" | "持有"
    symbol: str
    name: str
    reason: str
    price: float | None = None
    pnl_pct: float | None = None


def load_state() -> PortfolioState:
    if not STATE_PATH.exists():
        return PortfolioState()
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    holdings = [Holding(**h) for h in data.get("holdings", [])]
    return PortfolioState(holdings=holdings, last_run_date=data.get("last_run_date"))


def save_state(state: PortfolioState) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(STATE_PATH.parent), suffix=".tmp")
    payload = {
        "holdings": [asdict(h) for h in state.holdings],
        "last_run_date": state.last_run_date,
    }
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(STATE_PATH))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _score(metrics_by_symbol: dict[str, SymbolMetrics], symbol: str) -> float | None:
    m = metrics_by_symbol.get(symbol)
    return m.momentum_20d if m else None


def decide(
    state: PortfolioState,
    metrics_by_symbol: dict[str, SymbolMetrics],
    ranked_candidates: list[SymbolMetrics],
    as_of: str | None = None,
) -> tuple[list[Decision], PortfolioState]:
    """as_of: 决策发生的日期(ISO字符串)。实盘留空默认用今天；回测传入模拟中的历史日期，
    这样实盘和回测复用同一份决策逻辑，不用维护两套规则实现。"""
    decisions: list[Decision] = []
    remaining: list[Holding] = []

    for holding in state.holdings:
        m = metrics_by_symbol.get(holding.symbol)
        latest_price = m.latest_close if m else None
        pnl_pct = (latest_price / holding.entry_price - 1) if latest_price else None

        if m is None:
            decisions.append(Decision("卖出", holding.symbol, holding.name, "无法获取最新数据，保守离场"))
        elif pnl_pct is not None and pnl_pct <= -STOP_LOSS_PCT:
            decisions.append(
                Decision("卖出", holding.symbol, holding.name,
                          f"触发止损：较买入价{pnl_pct:.1%}", latest_price, pnl_pct)
            )
        elif not m.trend_ok:
            decisions.append(
                Decision("卖出", holding.symbol, holding.name,
                          "跌破20日均线，趋势确认失效", latest_price, pnl_pct)
            )
        else:
            remaining.append(holding)

    held_symbols = {h.symbol for h in remaining}
    open_slots = TARGET_HOLDINGS - len(remaining)
    new_buys: list[SymbolMetrics] = []

    if open_slots > 0:
        for cand in ranked_candidates:
            if len(new_buys) >= open_slots:
                break
            if cand.symbol in held_symbols:
                continue
            new_buys.append(cand)
    elif remaining and ranked_candidates:
        best_candidate = next((c for c in ranked_candidates if c.symbol not in held_symbols), None)
        weakest_score = min(
            (s for h in remaining if (s := _score(metrics_by_symbol, h.symbol)) is not None),
            default=None,
        )
        if best_candidate is not None and weakest_score is not None:
            edge = best_candidate.momentum_20d - weakest_score
            if edge > MIN_SCORE_EDGE:
                weakest_holding = min(
                    remaining,
                    key=lambda h: _score(metrics_by_symbol, h.symbol) or float("inf"),
                )
                decisions.append(
                    Decision(
                        "卖出", weakest_holding.symbol, weakest_holding.name,
                        f"换仓：候选动量分领先{edge:.1%}，超过换手成本+降噪缓冲",
                        metrics_by_symbol[weakest_holding.symbol].latest_close,
                    )
                )
                remaining = [h for h in remaining if h.symbol != weakest_holding.symbol]
                new_buys = [best_candidate]

    for cand in new_buys:
        decisions.append(
            Decision("买入", cand.symbol, cand.name,
                     f"20日动量排名靠前(动量{cand.momentum_20d:.1%})，满足趋势和流动性条件",
                     cand.latest_close)
        )

    for holding in remaining:
        m = metrics_by_symbol.get(holding.symbol)
        pnl_pct = (m.latest_close / holding.entry_price - 1) if m else None
        decisions.append(
            Decision("持有", holding.symbol, holding.name,
                     "仍满足趋势确认，未触发止损或换仓条件",
                     m.latest_close if m else None, pnl_pct)
        )

    today = as_of or date.today().isoformat()
    new_holdings = list(remaining) + [
        Holding(cand.symbol, cand.name, cand.latest_close, today) for cand in new_buys
    ]
    new_state = PortfolioState(holdings=new_holdings, last_run_date=today)
    return decisions, new_state
