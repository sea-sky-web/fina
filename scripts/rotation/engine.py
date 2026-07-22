from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StrategyConfig, DEFAULT_CONFIG


def target_symbols_hysteresis(
    score_row: pd.Series,
    current_weights: pd.Series,
    holdings: int,
    stopped_out: set[str],
    cooldown: set[str],
    buffer: int,
) -> list[str]:
    candidates = score_row.dropna()
    positive = candidates[candidates > 0]
    ranked = positive.sort_values(ascending=False)
    ranked_eligible = ranked[~ranked.index.isin(cooldown)]

    currently_held = set(current_weights[current_weights > 0].index) - stopped_out
    top_k_buffer = set(ranked_eligible.head(holdings + buffer).index)

    keep_candidates = currently_held & top_k_buffer
    keep_ranked = ranked_eligible[ranked_eligible.index.isin(keep_candidates)]
    keep_final = list(keep_ranked.head(holdings).index)

    open_slots = holdings - len(keep_final)
    new_candidates = [s for s in ranked_eligible.index if s not in keep_final]
    new_adds = new_candidates[: max(open_slots, 0)]
    return keep_final + new_adds


def target_weights(
    final_set: list[str],
    symbols: list[str],
    config: StrategyConfig = DEFAULT_CONFIG,
    bench_slot: bool = False,
) -> pd.Series:
    all_syms = symbols + [config.benchmark] if bench_slot else symbols
    weights = pd.Series(0.0, index=all_syms)
    if bench_slot:
        n_total = len(final_set) + 1
        per_weight = min(1.0 / n_total, config.max_symbol_weight)
        weights.loc[config.benchmark] = per_weight
        for s in final_set:
            weights.loc[s] = per_weight
    else:
        if not final_set:
            return weights
        per_weight = min(1.0 / len(final_set), config.max_symbol_weight)
        for s in final_set:
            weights.loc[s] = per_weight
    return weights


def simulate(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    close_full: pd.DataFrame,
    symbols: list[str],
    dates: pd.DatetimeIndex,
    holdings: int,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    score = score_full.reindex(dates)
    returns = returns_full.reindex(dates)
    prices = close_full.reindex(dates)

    bench_close = close_full[config.benchmark]
    bench_daily_ret = bench_close.pct_change().reindex(dates).fillna(0.0)
    bench_ma10 = bench_close.rolling(10).mean()
    bench_ma30 = bench_close.rolling(30).mean()
    bear_mask = (bench_ma10 < bench_ma30).reindex(dates).fillna(False)

    all_syms = symbols + [config.benchmark]
    current_weights = pd.Series(0.0, index=all_syms)
    entry_price: dict[str, float] = {}
    cooldown_until: dict[str, pd.Timestamp] = {}
    paused_until: pd.Timestamp | None = None
    records = []
    stop_loss_events = 0
    reentry_events = 0
    portfolio_equity = 1.0
    portfolio_peak = 1.0
    portfolio_dd_cooldown_until: pd.Timestamp | None = None
    bench_consecutive_up = 0
    reentry_bench_until: pd.Timestamp | None = None

    bench_returns = close_full[config.benchmark].pct_change().reindex(dates).fillna(0.0)

    for d in dates:
        day_price_sector = prices.loc[d].reindex(symbols)
        day_returns_sector = returns.loc[d].reindex(symbols).fillna(0.0)
        bench_ret_today = float(bench_returns.loc[d])

        day_returns_all = pd.Series(0.0, index=all_syms)
        day_returns_all[symbols] = day_returns_sector
        day_returns_all[config.benchmark] = bench_ret_today

        gross_return = float((current_weights * day_returns_all).sum())

        b_ret = float(bench_daily_ret.loc[d])
        if b_ret > 0:
            bench_consecutive_up += 1
        else:
            bench_consecutive_up = 0

        cooldown_active = {s for s, until in cooldown_until.items() if until >= d}

        stopped_out: set[str] = set()
        for sym in list(current_weights[current_weights > 0].index):
            if sym == config.benchmark:
                continue
            ep = entry_price.get(sym)
            price_now = day_price_sector.get(sym)
            if ep is None or pd.isna(price_now) or ep == 0:
                continue
            ret_since_entry = price_now / ep - 1
            if ret_since_entry <= config.stop_loss_threshold:
                stopped_out.add(sym)
                cooldown_until[sym] = d + pd.tseries.offsets.BDay(config.cooldown_days)
                stop_loss_events += 1

        in_dd_cooldown = (
            portfolio_dd_cooldown_until is not None and d <= portfolio_dd_cooldown_until
        )
        if in_dd_cooldown:
            reentry_signal = (
                b_ret >= config.reentry_bench_spike
                or bench_consecutive_up >= config.reentry_consecutive_up
            )
            if reentry_signal:
                portfolio_dd_cooldown_until = None
                in_dd_cooldown = False
                reentry_events += 1
                reentry_bench_until = d + pd.tseries.offsets.BDay(config.reentry_bench_days)
                portfolio_peak = portfolio_equity * (1 + config.reentry_peak_buffer)

        use_bench_slot = reentry_bench_until is not None and d <= reentry_bench_until

        if paused_until is not None and d <= paused_until:
            final_set = [
                s
                for s in current_weights[current_weights > 0].index
                if s not in stopped_out and s != config.benchmark
            ]
        elif in_dd_cooldown:
            final_set = []
            use_bench_slot = False
        else:
            row_score = score.loc[d].reindex(symbols)
            sector_slots = max(holdings - 1, 1) if use_bench_slot else holdings
            final_set = target_symbols_hysteresis(
                row_score,
                current_weights.reindex(symbols),
                sector_slots,
                stopped_out,
                cooldown_active,
                config.hysteresis_buffer,
            )

        target = target_weights(final_set, symbols, config, bench_slot=use_bench_slot)

        if bear_mask.loc[d]:
            target = target * config.bear_scale
        else:
            target = target * config.bull_boost

        current_weights = current_weights.reindex(all_syms, fill_value=0.0)
        target = target.reindex(all_syms, fill_value=0.0)

        delta = target - current_weights
        planned_turnover = float(delta.abs().sum())
        if planned_turnover > config.max_daily_turnover and planned_turnover > 0:
            scale = config.max_daily_turnover / planned_turnover
            target = current_weights + delta * scale
            planned_turnover = config.max_daily_turnover

        cost = planned_turnover * config.cost_rate_one_side
        net_return = gross_return - cost

        if net_return <= config.circuit_breaker_daily_loss:
            paused_until = d + pd.tseries.offsets.BDay(1)

        for sym in all_syms:
            was_held = current_weights.get(sym, 0.0) > 0
            now_held = target.get(sym, 0.0) > 0
            if sym == config.benchmark:
                continue
            if now_held and not was_held:
                entry_price[sym] = day_price_sector.get(sym, np.nan)
            elif not now_held and was_held:
                entry_price.pop(sym, None)

        current_weights = target
        portfolio_equity *= 1 + net_return
        portfolio_peak = max(portfolio_peak, portfolio_equity)
        portfolio_dd = portfolio_equity / portfolio_peak - 1
        if portfolio_dd <= config.portfolio_dd_threshold and (
            portfolio_dd_cooldown_until is None or d > portfolio_dd_cooldown_until
        ):
            portfolio_dd_cooldown_until = d + pd.tseries.offsets.BDay(
                config.portfolio_dd_cooldown
            )
        records.append(
            {
                "date": d,
                "gross_return": gross_return,
                "cost": cost,
                "net_return": net_return,
                "turnover": planned_turnover,
                "n_holdings": int((current_weights > 0).sum()),
            }
        )

    result = pd.DataFrame(records).set_index("date")
    result.attrs["stop_loss_events"] = stop_loss_events
    result.attrs["reentry_events"] = reentry_events
    return result
