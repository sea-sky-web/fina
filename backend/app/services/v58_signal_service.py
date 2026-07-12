"""V58 ETF sector rotation signal service.

Implements the V58 strategy (best profit-focused configuration from 60-iteration
walk-forward optimization) as a backend service. Core components:
- Dual-period momentum z-score (L=10, L=20)
- 60-day relative strength percentile vs benchmark
- Dynamic factor weights based on MA20/MA60 regime
- Volume-price confirmation (bull-market only)
- Bear-market position scaling (MA10/MA30)
- Hysteresis buffer for turnover control
- Individual stop-loss with cooldown
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.config import PROJECT_ROOT, settings
from app.models import (
    V58Config,
    V58PortfolioState,
    V58SignalReport,
    V58SymbolSignal,
)
from app.services.v58_state import V58PersistentState, load_state, save_state

BENCHMARK = "510300.SH"

K = 3
MAX_SYMBOL_WEIGHT = 0.25
HYSTERESIS_BUFFER = 3
STOP_LOSS_THRESHOLD = -0.05
COOLDOWN_DAYS = 5
BULL_BOOST = 1.50
BEAR_SCALE = 0.50
VOLUME_THRESHOLD = 1.15
VOLUME_BONUS = 0.3
MOMENTUM_LOOKBACKS = [10, 20]
REL_STRENGTH_LOOKBACK = 60

_UNIVERSE_PATH = PROJECT_ROOT / "config" / "v58_universe.csv"
_RESEARCH_DATA = PROJECT_ROOT / "data" / "research" / "etf_daily_backtest.parquet"


def _load_universe() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    if not _UNIVERSE_PATH.exists():
        return result
    with open(_UNIVERSE_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[row["symbol"]] = {"name": row["name"], "theme": row.get("theme", "")}
    return result


def _load_daily_data() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    if _RESEARCH_DATA.exists():
        raw = pd.read_parquet(_RESEARCH_DATA)
    else:
        clean_path = Path(settings.clean_dir) / "etf_daily.parquet"
        raw = pd.read_parquet(clean_path)

    raw["date"] = pd.to_datetime(raw["date"])
    close = raw.pivot(index="date", columns="symbol", values="close").sort_index()
    amount = raw.pivot(index="date", columns="symbol", values="amount").sort_index()
    close = close.ffill(limit=2)
    amount = amount.ffill(limit=2)

    universe = _load_universe()
    symbols = [s for s in universe if s in close.columns]
    return close, amount, symbols


def _vectorized_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    mean = frame.mean(axis=1)
    std = frame.std(axis=1, ddof=0).replace(0, np.nan)
    z = frame.sub(mean, axis=0).div(std, axis=0)
    return z.fillna(0.0)


def _vectorized_pct_rank(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rank(axis=1, pct=True).fillna(0.5)


def _compute_scores(
    close: pd.DataFrame,
    amount: pd.DataFrame,
    symbols: list[str],
) -> pd.DataFrame:
    mom_components = []
    for lookback in MOMENTUM_LOOKBACKS:
        ret = close[symbols].pct_change(lookback)
        mom_components.append(_vectorized_zscore(ret))
    mom_z = sum(mom_components) / len(mom_components)

    bench = close[BENCHMARK]
    bench_ret_long = bench.pct_change(REL_STRENGTH_LOOKBACK)
    ret_long = close[symbols].pct_change(REL_STRENGTH_LOOKBACK)
    excess_long = ret_long.sub(bench_ret_long, axis=0)
    rel_rank = _vectorized_pct_rank(excess_long)

    ma20 = bench.rolling(20).mean()
    ma60 = bench.rolling(60).mean()
    bear_mask = (ma20 < ma60).reindex(close.index).fillna(False)

    w_mom = pd.Series(0.55, index=close.index)
    w_rel = pd.Series(0.45, index=close.index)
    w_mom[bear_mask] = 0.35
    w_rel[bear_mask] = 0.65

    score = mom_z.mul(w_mom, axis=0) + rel_rank.mul(w_rel, axis=0)

    vol_ratio = amount[symbols].rolling(5).mean() / amount[symbols].rolling(20).mean()
    price_up = close[symbols].pct_change(5) > 0
    volume_confirmed = (vol_ratio > VOLUME_THRESHOLD) & price_up
    volume_bonus = pd.DataFrame(0.0, index=close.index, columns=symbols)
    volume_bonus[volume_confirmed] = VOLUME_BONUS
    price_down_vol_up = (vol_ratio > VOLUME_THRESHOLD) & ~price_up
    volume_bonus[price_down_vol_up] = -VOLUME_BONUS
    volume_bonus[bear_mask] = 0.0
    score = score + volume_bonus

    score[excess_long.isna()] = np.nan
    return score


def _detect_factor_regime(close: pd.DataFrame, d: pd.Timestamp) -> str:
    bench = close[BENCHMARK]
    ma20 = bench.rolling(20).mean()
    ma60 = bench.rolling(60).mean()
    if d in ma20.index and d in ma60.index:
        if ma20.loc[d] < ma60.loc[d]:
            return "bear"
    return "bull"


def _detect_position_regime(close: pd.DataFrame, d: pd.Timestamp) -> tuple[str, float]:
    bench = close[BENCHMARK]
    ma10 = bench.rolling(10).mean()
    ma30 = bench.rolling(30).mean()
    if d in ma10.index and d in ma30.index:
        if ma10.loc[d] < ma30.loc[d]:
            return "bear", BEAR_SCALE
    return "bull", BULL_BOOST


def _select_with_hysteresis(
    score_row: pd.Series,
    current_holdings: list[str],
    stopped_out: set[str],
    cooldowns: set[str],
) -> list[str]:
    candidates = score_row.dropna()
    positive = candidates[candidates > 0]
    ranked = positive.sort_values(ascending=False)
    excluded = cooldowns | stopped_out
    ranked_eligible = ranked[~ranked.index.isin(excluded)]

    currently_held = set(current_holdings) - stopped_out
    top_k_buffer = set(ranked_eligible.head(K + HYSTERESIS_BUFFER).index)

    keep_candidates = currently_held & top_k_buffer
    keep_ranked = ranked_eligible[ranked_eligible.index.isin(keep_candidates)]
    keep_final = list(keep_ranked.head(K).index)

    open_slots = K - len(keep_final)
    new_candidates = [s for s in ranked_eligible.index if s not in keep_final]
    new_adds = new_candidates[: max(open_slots, 0)]
    return keep_final + new_adds


def _compute_target_weights(selected: list[str], position_scale: float) -> dict[str, float]:
    if not selected:
        return {}
    per_weight = min(1.0 / len(selected), MAX_SYMBOL_WEIGHT)
    scaled = per_weight * position_scale
    return {s: round(scaled, 4) for s in selected}


def generate_v58_signal(signal_date: date | None = None) -> V58SignalReport:
    universe = _load_universe()
    close, amount, symbols = _load_daily_data()
    notes: list[str] = []

    missing = [s for s in universe if s not in symbols]
    if missing:
        notes.append(f"标的缺失: {missing}")

    if not symbols:
        return V58SignalReport(
            signal_date=signal_date or date.today(),
            portfolio_state=V58PortfolioState(signal_date=signal_date or date.today()),
            data_notes=["无可用标的数据"],
        )

    latest_date = close.index[-1]
    if signal_date:
        target = pd.Timestamp(signal_date)
        if target in close.index:
            latest_date = target
        else:
            idx = close.index.get_indexer([target], method="ffill")
            if idx[0] >= 0:
                latest_date = close.index[idx[0]]
                notes.append(f"请求日期 {signal_date} 无数据，使用 {latest_date.date()}")
    else:
        signal_date = latest_date.date()

    scores = _compute_scores(close, amount, symbols)
    score_row = scores.loc[latest_date].reindex(symbols)

    factor_regime = _detect_factor_regime(close, latest_date)
    position_regime, position_scale = _detect_position_regime(close, latest_date)

    state = load_state()

    today_str = str(signal_date)
    cooldown_active: set[str] = set()
    for sym, until_str in state.cooldown_until.items():
        if until_str >= today_str:
            cooldown_active.add(sym)

    stopped_out: set[str] = set()
    day_price = close.loc[latest_date].reindex(symbols)
    for sym in list(state.current_holdings):
        ep = state.entry_prices.get(sym)
        price_now = day_price.get(sym)
        if ep is None or pd.isna(price_now) or ep == 0:
            continue
        ret_since_entry = price_now / ep - 1
        if ret_since_entry <= STOP_LOSS_THRESHOLD:
            stopped_out.add(sym)
            cooldown_end = signal_date + timedelta(days=COOLDOWN_DAYS + 2)
            state.cooldown_until[sym] = str(cooldown_end)

    selected = _select_with_hysteresis(
        score_row, state.current_holdings, stopped_out, cooldown_active
    )
    weights = _compute_target_weights(selected, position_scale)
    total_exposure = sum(weights.values())

    for sym in symbols:
        was_held = sym in state.current_holdings
        now_held = sym in selected
        if now_held and not was_held:
            price = day_price.get(sym)
            if price and not pd.isna(price):
                state.entry_prices[sym] = float(price)
        elif not now_held and was_held:
            state.entry_prices.pop(sym, None)

    state.last_signal_date = today_str
    state.current_holdings = list(selected)
    for sym in stopped_out:
        state.entry_prices.pop(sym, None)

    mom_z_all = sum(
        _vectorized_zscore(close[symbols].pct_change(lb)) for lb in MOMENTUM_LOOKBACKS
    ) / len(MOMENTUM_LOOKBACKS)
    bench_ret = close[BENCHMARK].pct_change(REL_STRENGTH_LOOKBACK)
    ret_long = close[symbols].pct_change(REL_STRENGTH_LOOKBACK)
    excess = ret_long.sub(bench_ret, axis=0)
    rel_rank_all = _vectorized_pct_rank(excess)

    signals_list: list[V58SymbolSignal] = []
    for i, (sym, sc) in enumerate(score_row.sort_values(ascending=False).items()):
        if pd.isna(sc):
            continue
        info = universe.get(sym, {"name": sym, "theme": ""})
        mom_val = float(mom_z_all.loc[latest_date, sym]) if sym in mom_z_all.columns else 0.0
        rel_val = float(rel_rank_all.loc[latest_date, sym]) if sym in rel_rank_all.columns else 0.0
        cd_until = state.cooldown_until.get(sym)
        cd_date = date.fromisoformat(cd_until) if cd_until and cd_until >= today_str else None

        sig = V58SymbolSignal(
            symbol=sym,
            name=info["name"],
            theme=info.get("theme", ""),
            momentum_z=round(mom_val, 4),
            relative_strength_pct=round(rel_val, 4),
            volume_price_bonus=0.0,
            raw_score=round(float(sc), 4),
            final_score=round(float(sc), 4),
            rank=i + 1,
            selected=sym in selected,
            target_weight=weights.get(sym, 0.0),
            stop_loss_active=sym in stopped_out,
            cooldown_until=cd_date,
        )
        signals_list.append(sig)

    selected_signals = [s for s in signals_list if s.selected]

    save_state(state)

    return V58SignalReport(
        signal_date=signal_date,
        config=V58Config(),
        portfolio_state=V58PortfolioState(
            signal_date=signal_date,
            factor_regime=factor_regime,
            position_regime=position_regime,
            position_scale=position_scale,
            total_exposure=round(total_exposure, 4),
            cash_weight=round(max(0, 1 - total_exposure), 4),
            n_holdings=len(selected),
        ),
        signals=signals_list,
        selected=selected_signals,
        data_notes=notes,
    )
