"""ETF sector rotation signal service.

复用 app.rotation_engine 回测内核生成每日轮动信号，保证「回测验证的逻辑」
与「线上信号逻辑」为同一份代码：
- 评分：rotation_engine.signals.compute_scores（双周期动量 z-score +
  相对强弱百分位 + 量价确认 + 牛熊因子权重切换）
- 选股：rotation_engine.engine.target_symbols_hysteresis（滞回缓冲控换手）
策略参数（版本、K、止损、冷却等）来自 config/strategy.json，见
app.services.strategy_config。
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from app.core.config import settings
from app.models import (
    StrategyParams,
    StrategyPortfolioState,
    StrategySignalReport,
    StrategySymbolSignal,
)
from app.rotation_engine.config import StrategyConfig as EngineConfig
from app.rotation_engine.engine import target_symbols_hysteresis
from app.rotation_engine.signals import (
    compute_scores,
    vectorized_pct_rank,
    vectorized_zscore,
)
from app.services.strategy_config import load_strategy_params, universe_path
from app.services.strategy_state import load_state, save_state

_RESEARCH_DATA_REL = Path("data") / "research" / "etf_daily_backtest.parquet"


def _load_universe() -> dict[str, dict[str, str]]:
    path = universe_path()
    result: dict[str, dict[str, str]] = {}
    if not path.exists():
        return result
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[row["symbol"]] = {"name": row["name"], "theme": row.get("theme", "")}
    return result


def _load_daily_data() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    research_path = Path(settings.data_dir).parent / _RESEARCH_DATA_REL
    if research_path.exists():
        raw = pd.read_parquet(research_path)
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


def _engine_config(params: StrategyParams) -> EngineConfig:
    return EngineConfig(
        benchmark=params.benchmark,
        momentum_lookback_set=list(params.momentum_lookbacks),
        rel_strength_lookback=params.rel_strength_lookback,
        hysteresis_buffer=params.hysteresis_buffer,
        stop_loss_threshold=params.stop_loss_threshold,
        cooldown_days=params.cooldown_days,
        bear_scale=params.bear_scale,
        bull_boost=params.bull_boost,
        max_symbol_weight=params.max_symbol_weight,
    )


def _detect_factor_regime(close: pd.DataFrame, params: StrategyParams, d: pd.Timestamp) -> str:
    bench = close[params.benchmark]
    ma20 = bench.rolling(20).mean()
    ma60 = bench.rolling(60).mean()
    if d in ma20.index and d in ma60.index:
        if ma20.loc[d] < ma60.loc[d]:
            return "bear"
    return "bull"


def _detect_position_regime(
    close: pd.DataFrame, params: StrategyParams, d: pd.Timestamp
) -> tuple[str, float]:
    bench = close[params.benchmark]
    ma10 = bench.rolling(10).mean()
    ma30 = bench.rolling(30).mean()
    if d in ma10.index and d in ma30.index:
        if ma10.loc[d] < ma30.loc[d]:
            return "bear", params.bear_scale
    return "bull", params.bull_boost


def _compute_target_weights(
    selected: list[str], position_scale: float, params: StrategyParams
) -> dict[str, float]:
    if not selected:
        return {}
    per_weight = min(1.0 / len(selected), params.max_symbol_weight)
    scaled = per_weight * position_scale
    return {s: round(scaled, 4) for s in selected}


def generate_strategy_signal(signal_date: date | None = None) -> StrategySignalReport:
    params = load_strategy_params()
    universe = _load_universe()
    close, amount, symbols = _load_daily_data()
    notes: list[str] = []

    missing = [s for s in universe if s not in symbols]
    if missing:
        notes.append(f"标的缺失: {missing}")

    if not symbols:
        return StrategySignalReport(
            signal_date=signal_date or date.today(),
            config=params,
            portfolio_state=StrategyPortfolioState(signal_date=signal_date or date.today()),
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

    engine_cfg = _engine_config(params)
    scores = compute_scores(close, symbols, amount, engine_cfg)
    score_row = scores.loc[latest_date].reindex(symbols)

    factor_regime = _detect_factor_regime(close, params, latest_date)
    position_regime, position_scale = _detect_position_regime(close, params, latest_date)

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
        if ret_since_entry <= params.stop_loss_threshold:
            stopped_out.add(sym)
            cooldown_end = signal_date + timedelta(days=params.cooldown_days + 2)
            state.cooldown_until[sym] = str(cooldown_end)

    current_weights = pd.Series(0.0, index=symbols)
    for sym in state.current_holdings:
        if sym in current_weights.index:
            current_weights[sym] = 1.0
    selected = target_symbols_hysteresis(
        score_row,
        current_weights,
        params.k,
        stopped_out,
        cooldown_active | stopped_out,
        params.hysteresis_buffer,
    )
    weights = _compute_target_weights(selected, position_scale, params)
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
        vectorized_zscore(close[symbols].pct_change(lb)) for lb in params.momentum_lookbacks
    ) / len(params.momentum_lookbacks)
    bench_ret = close[params.benchmark].pct_change(params.rel_strength_lookback)
    ret_long = close[symbols].pct_change(params.rel_strength_lookback)
    excess = ret_long.sub(bench_ret, axis=0)
    rel_rank_all = vectorized_pct_rank(excess)

    signals_list: list[StrategySymbolSignal] = []
    for i, (sym, sc) in enumerate(score_row.sort_values(ascending=False).items()):
        if pd.isna(sc):
            continue
        info = universe.get(sym, {"name": sym, "theme": ""})
        mom_val = float(mom_z_all.loc[latest_date, sym]) if sym in mom_z_all.columns else 0.0
        rel_val = float(rel_rank_all.loc[latest_date, sym]) if sym in rel_rank_all.columns else 0.0
        cd_until = state.cooldown_until.get(sym)
        cd_date = date.fromisoformat(cd_until) if cd_until and cd_until >= today_str else None

        sig = StrategySymbolSignal(
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

    return StrategySignalReport(
        signal_date=signal_date,
        config=params,
        portfolio_state=StrategyPortfolioState(
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
