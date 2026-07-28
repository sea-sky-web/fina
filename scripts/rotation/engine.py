from __future__ import annotations

import numpy as np
import pandas as pd

from .config import ClassConfig, StrategyConfig, DEFAULT_CONFIG, TRADING_DAYS_PER_YEAR


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


def _multi_signal_regime_scale(
    bench_close: pd.Series,
    dates: pd.DatetimeIndex,
    bear_scale: float,
    bull_boost: float,
) -> pd.Series:
    """四信号投票 regime 检测,替代单一 MA10/MA30 交叉判断.

    信号(每日各产生看多/看空一票):
      1. MA5 > MA20   (快,2-3日反应)
      2. RSI(5) > 70  (极快,1日反应,捕捉超卖反弹)
      3. 3日涨幅 > 5%  (极快,1日反应,捕捉暴涨确认)
      4. MA10 > MA30  (慢,原有趋势确认信号)

    票数 >=3 看多 -> 牛市模式(bull_boost)
    票数 <=1 看多 -> 熊市模式(bear_scale)
    票数 ==2      -> 中性模式(两者均值), 渐进过渡, 减少反转时的滞后踏空
    """
    ma5 = bench_close.rolling(5).mean()
    ma10 = bench_close.rolling(10).mean()
    ma20 = bench_close.rolling(20).mean()
    ma30 = bench_close.rolling(30).mean()

    delta = bench_close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(5).mean()
    avg_loss = loss.rolling(5).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi5 = 100 - (100 / (1 + rs))
    rsi5 = rsi5.where(avg_loss != 0, 100.0)

    mom3 = bench_close.pct_change(3)

    vote_ma_fast = (ma5 > ma20).astype(int)
    vote_rsi = (rsi5 > 70).astype(int)
    vote_mom = (mom3 > 0.05).astype(int)
    vote_ma_slow = (ma10 > ma30).astype(int)

    votes = (vote_ma_fast + vote_rsi + vote_mom + vote_ma_slow).reindex(dates).fillna(0)

    neutral_scale = (bear_scale + bull_boost) / 2.0
    scale = pd.Series(bear_scale, index=dates)
    scale[votes == 2] = neutral_scale
    scale[votes >= 3] = bull_boost
    return scale


def target_weights(
    final_set: list[str],
    symbols: list[str],
    benchmark: str,
    max_symbol_weight: float = 0.25,
    bench_slot: bool = False,
) -> pd.Series:
    all_syms = symbols + [benchmark] if bench_slot else symbols
    weights = pd.Series(0.0, index=all_syms)
    if bench_slot:
        n_total = len(final_set) + 1
        per_weight = min(1.0 / n_total, max_symbol_weight)
        weights.loc[benchmark] = per_weight
        for s in final_set:
            weights.loc[s] = per_weight
    else:
        if not final_set:
            return weights
        per_weight = min(1.0 / len(final_set), max_symbol_weight)
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
    class_config: ClassConfig | None = None,
    record_weights: bool = False,
) -> pd.DataFrame:
    """模拟引擎.

    当 class_config 不为 None 时，使用其中的风控参数覆盖 config 中的默认值,
    实现多资产模式下每类独立的风控阈值.

    record_weights=True 时,每条记录额外附带当日权重快照、regime_scale、
    止损/暂停/回撤保护等状态标签,用于逐日持仓复盘(不影响默认行为).
    """
    benchmark = class_config.benchmark if class_config else config.benchmark
    stop_loss_threshold = (
        class_config.stop_loss_threshold if class_config else config.stop_loss_threshold
    )
    cooldown_days = (
        class_config.cooldown_days if class_config else config.cooldown_days
    )
    circuit_breaker = (
        class_config.circuit_breaker_daily_loss
        if class_config else config.circuit_breaker_daily_loss
    )
    dd_threshold = (
        class_config.portfolio_dd_threshold
        if class_config else config.portfolio_dd_threshold
    )
    dd_cooldown = (
        class_config.portfolio_dd_cooldown
        if class_config else config.portfolio_dd_cooldown
    )
    reentry_spike = (
        class_config.reentry_bench_spike if class_config else config.reentry_bench_spike
    )
    reentry_consec = (
        class_config.reentry_consecutive_up
        if class_config else config.reentry_consecutive_up
    )
    reentry_days = (
        class_config.reentry_bench_days if class_config else config.reentry_bench_days
    )
    reentry_buffer = (
        class_config.reentry_peak_buffer if class_config else config.reentry_peak_buffer
    )
    bear_scale = class_config.bear_scale if class_config else config.bear_scale
    bull_boost = class_config.bull_boost if class_config else config.bull_boost
    cost_rate = (
        class_config.cost_rate_one_side if class_config else config.cost_rate_one_side
    )
    max_turnover = (
        class_config.max_daily_turnover if class_config else config.max_daily_turnover
    )
    max_weight = (
        class_config.max_symbol_weight if class_config else config.max_symbol_weight
    )
    hysteresis = (
        class_config.hysteresis_buffer if class_config else config.hysteresis_buffer
    )

    score = score_full.reindex(dates)
    returns = returns_full.reindex(dates)
    prices = close_full.reindex(dates)

    bench_close = close_full[benchmark]
    bench_daily_ret = bench_close.pct_change().reindex(dates).fillna(0.0)
    regime_scale = _multi_signal_regime_scale(bench_close, dates, bear_scale, bull_boost)

    symbols_no_bench = [s for s in symbols if s != benchmark]
    all_syms = symbols_no_bench + [benchmark]
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

    bench_returns = close_full[benchmark].pct_change().reindex(dates).fillna(0.0)

    for d in dates:
        day_price_sector = prices.loc[d].reindex(symbols_no_bench)
        day_returns_sector = returns.loc[d].reindex(symbols_no_bench).fillna(0.0)
        bench_ret_today = float(bench_returns.loc[d])

        day_returns_all = pd.Series(0.0, index=all_syms)
        day_returns_all[symbols_no_bench] = day_returns_sector
        day_returns_all[benchmark] = bench_ret_today

        weights_before = current_weights.copy()
        contributions = current_weights * day_returns_all
        gross_return = float(contributions.sum())

        b_ret = float(bench_daily_ret.loc[d])
        if b_ret > 0:
            bench_consecutive_up += 1
        else:
            bench_consecutive_up = 0

        cooldown_active = {s for s, until in cooldown_until.items() if until >= d}

        stopped_out: set[str] = set()
        for sym in list(current_weights[current_weights > 0].index):
            if sym == benchmark:
                continue
            ep = entry_price.get(sym)
            price_now = day_price_sector.get(sym)
            if ep is None or pd.isna(price_now) or ep == 0:
                continue
            ret_since_entry = price_now / ep - 1
            if ret_since_entry <= stop_loss_threshold:
                stopped_out.add(sym)
                cooldown_until[sym] = d + pd.tseries.offsets.BDay(cooldown_days)
                stop_loss_events += 1

        in_dd_cooldown = (
            portfolio_dd_cooldown_until is not None and d <= portfolio_dd_cooldown_until
        )
        if in_dd_cooldown:
            reentry_signal = (
                b_ret >= reentry_spike
                or bench_consecutive_up >= reentry_consec
            )
            if reentry_signal:
                portfolio_dd_cooldown_until = None
                in_dd_cooldown = False
                reentry_events += 1
                reentry_bench_until = d + pd.tseries.offsets.BDay(reentry_days)
                portfolio_peak = portfolio_equity * (1 + reentry_buffer)

        use_bench_slot = reentry_bench_until is not None and d <= reentry_bench_until

        if paused_until is not None and d <= paused_until:
            final_set = [
                s
                for s in current_weights[current_weights > 0].index
                if s not in stopped_out and s != benchmark
            ]
        elif in_dd_cooldown:
            final_set = []
            use_bench_slot = False
        else:
            row_score = score.loc[d].reindex(symbols_no_bench)
            sector_slots = max(holdings - 1, 1) if use_bench_slot else holdings
            final_set = target_symbols_hysteresis(
                row_score,
                current_weights.reindex(symbols_no_bench),
                sector_slots,
                stopped_out,
                cooldown_active,
                hysteresis,
            )

        target = target_weights(
            final_set, symbols_no_bench, benchmark, max_weight, bench_slot=use_bench_slot,
        )

        target = target * regime_scale.loc[d]

        current_weights = current_weights.reindex(all_syms, fill_value=0.0)
        target = target.reindex(all_syms, fill_value=0.0)

        total_exposure = float(target.sum())
        leverage_cost = 0.0
        if total_exposure > 1.0:
            leverage_cost = (total_exposure - 1.0) * (0.03 / TRADING_DAYS_PER_YEAR)

        delta = target - current_weights
        planned_turnover = float(delta.abs().sum())
        if planned_turnover > max_turnover and planned_turnover > 0:
            scale = max_turnover / planned_turnover
            target = current_weights + delta * scale
            planned_turnover = max_turnover

        cost = planned_turnover * cost_rate
        net_return = gross_return - cost - leverage_cost

        circuit_triggered = net_return <= circuit_breaker
        if circuit_triggered:
            paused_until = d + pd.tseries.offsets.BDay(1)
            target = current_weights.copy()
            planned_turnover = 0.0
            cost = 0.0
            net_return = gross_return

        for sym in all_syms:
            was_held = current_weights.get(sym, 0.0) > 0
            now_held = target.get(sym, 0.0) > 0
            if sym == benchmark:
                continue
            if now_held and not was_held:
                entry_price[sym] = day_price_sector.get(sym, np.nan)
            elif not now_held and was_held:
                entry_price.pop(sym, None)

        current_weights = target
        portfolio_equity *= 1 + net_return
        portfolio_peak = max(portfolio_peak, portfolio_equity)
        portfolio_dd = portfolio_equity / portfolio_peak - 1
        if portfolio_dd <= dd_threshold and (
            portfolio_dd_cooldown_until is None or d > portfolio_dd_cooldown_until
        ):
            portfolio_dd_cooldown_until = d + pd.tseries.offsets.BDay(dd_cooldown)
        records.append(
            {
                "date": d,
                "gross_return": gross_return,
                "cost": cost,
                "net_return": net_return,
                "turnover": planned_turnover,
                "n_holdings": int((current_weights > 0).sum()),
                **(
                    {
                        "weights_before": weights_before.to_dict(),
                        "weights_after": current_weights.to_dict(),
                        "contributions": contributions.to_dict(),
                        "returns": day_returns_all.to_dict(),
                        "regime_scale": float(regime_scale.loc[d]),
                        "stopped_out": sorted(stopped_out),
                        "circuit_triggered": bool(circuit_triggered),
                        "in_dd_cooldown": bool(in_dd_cooldown),
                        "use_bench_slot": bool(use_bench_slot),
                    }
                    if record_weights
                    else {}
                ),
            }
        )

    result = pd.DataFrame(records).set_index("date")
    result.attrs["stop_loss_events"] = stop_loss_events
    result.attrs["reentry_events"] = reentry_events
    return result
