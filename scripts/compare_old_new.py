"""对比新旧引擎: 方案A(去杠杆) + 方案B(多信号regime) 改进效果验证."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np
import pandas as pd

from rotation.config import DEFAULT_CONFIG, TRADING_DAYS_PER_YEAR
from rotation.data import load_data, liquidity_filter
from rotation.signals import compute_scores
from rotation.engine import (
    simulate,
    target_symbols_hysteresis,
    target_weights,
    _multi_signal_regime_scale,
)


def simulate_old(score_full, returns_full, close_full, symbols, dates, holdings, config):
    """旧版引擎: bull_boost=1.50, 二元 MA10/MA30 判断(无中性档,无杠杆成本扣除)."""
    benchmark = config.benchmark
    old_bull_boost = 1.50
    bear_scale = config.bear_scale

    score = score_full.reindex(dates)
    returns = returns_full.reindex(dates)
    prices = close_full.reindex(dates)

    bench_close = close_full[benchmark]
    bench_daily_ret = bench_close.pct_change().reindex(dates).fillna(0.0)
    bench_ma10 = bench_close.rolling(10).mean()
    bench_ma30 = bench_close.rolling(30).mean()
    bear_mask = (bench_ma10 < bench_ma30).reindex(dates).fillna(False)

    symbols_no_bench = [s for s in symbols if s != benchmark]
    all_syms = symbols_no_bench + [benchmark]
    current_weights = pd.Series(0.0, index=all_syms)
    entry_price = {}
    cooldown_until = {}
    paused_until = None
    records = []
    portfolio_equity = 1.0
    portfolio_peak = 1.0
    portfolio_dd_cooldown_until = None
    bench_consecutive_up = 0
    reentry_bench_until = None
    bench_returns = close_full[benchmark].pct_change().reindex(dates).fillna(0.0)

    for d in dates:
        day_price_sector = prices.loc[d].reindex(symbols_no_bench)
        day_returns_sector = returns.loc[d].reindex(symbols_no_bench).fillna(0.0)
        bench_ret_today = float(bench_returns.loc[d])
        day_returns_all = pd.Series(0.0, index=all_syms)
        day_returns_all[symbols_no_bench] = day_returns_sector
        day_returns_all[benchmark] = bench_ret_today
        gross_return = float((current_weights * day_returns_all).sum())

        b_ret = float(bench_daily_ret.loc[d])
        bench_consecutive_up = bench_consecutive_up + 1 if b_ret > 0 else 0
        cooldown_active = {s for s, until in cooldown_until.items() if until >= d}

        stopped_out = set()
        for sym in list(current_weights[current_weights > 0].index):
            if sym == benchmark:
                continue
            ep = entry_price.get(sym)
            price_now = day_price_sector.get(sym)
            if ep is None or pd.isna(price_now) or ep == 0:
                continue
            if price_now / ep - 1 <= config.stop_loss_threshold:
                stopped_out.add(sym)
                cooldown_until[sym] = d + pd.tseries.offsets.BDay(config.cooldown_days)

        in_dd_cooldown = portfolio_dd_cooldown_until is not None and d <= portfolio_dd_cooldown_until
        if in_dd_cooldown:
            if b_ret >= config.reentry_bench_spike or bench_consecutive_up >= config.reentry_consecutive_up:
                portfolio_dd_cooldown_until = None
                in_dd_cooldown = False
                reentry_bench_until = d + pd.tseries.offsets.BDay(config.reentry_bench_days)
                portfolio_peak = portfolio_equity * (1 + config.reentry_peak_buffer)

        use_bench_slot = reentry_bench_until is not None and d <= reentry_bench_until

        if paused_until is not None and d <= paused_until:
            final_set = [s for s in current_weights[current_weights > 0].index if s not in stopped_out and s != benchmark]
        elif in_dd_cooldown:
            final_set = []
            use_bench_slot = False
        else:
            row_score = score.loc[d].reindex(symbols_no_bench)
            sector_slots = max(holdings - 1, 1) if use_bench_slot else holdings
            final_set = target_symbols_hysteresis(
                row_score, current_weights.reindex(symbols_no_bench),
                sector_slots, stopped_out, cooldown_active, config.hysteresis_buffer,
            )

        target = target_weights(final_set, symbols_no_bench, benchmark, config.max_symbol_weight, bench_slot=use_bench_slot)

        # 旧逻辑: 二元判断, 无中性档, 牛市150%杠杆, 无融资成本扣除
        if bear_mask.loc[d]:
            target = target * bear_scale
        else:
            target = target * old_bull_boost

        current_weights = current_weights.reindex(all_syms, fill_value=0.0)
        target = target.reindex(all_syms, fill_value=0.0)

        delta = target - current_weights
        planned_turnover = float(delta.abs().sum())
        if planned_turnover > config.max_daily_turnover and planned_turnover > 0:
            scale = config.max_daily_turnover / planned_turnover
            target = current_weights + delta * scale
            planned_turnover = config.max_daily_turnover

        cost = planned_turnover * config.cost_rate_one_side
        net_return = gross_return - cost  # 旧版: 无杠杆成本扣除

        if net_return <= config.circuit_breaker_daily_loss:
            paused_until = d + pd.tseries.offsets.BDay(1)
            # 旧版bug: 熔断时权重已经更新, 不回退(复现旧行为用于对比)

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
        if portfolio_dd <= config.portfolio_dd_threshold and (portfolio_dd_cooldown_until is None or d > portfolio_dd_cooldown_until):
            portfolio_dd_cooldown_until = d + pd.tseries.offsets.BDay(config.portfolio_dd_cooldown)

        records.append({"date": d, "net_return": net_return})

    return pd.DataFrame(records).set_index("date")


def main():
    config = DEFAULT_CONFIG  # 已是新版: bull_boost=1.00
    close, amount, symbols = load_data(config)
    symbols = liquidity_filter(amount, symbols, config)
    day_counts = close[symbols].count()
    symbols = [s for s in symbols if day_counts.get(s, 0) >= config.min_history_days]
    print(f"[universe] {len(symbols)} symbols")

    score_full = compute_scores(close, symbols, amount, config)
    returns_full = close.pct_change(fill_method=None)

    all_dates = close.index.sort_values()
    bench_close_all = close[config.benchmark]

    # 月度窗口: 2021-01 ~ 最新有效月
    valid_mask = bench_close_all.pct_change().abs() > 0
    real_dates = all_dates[valid_mask.reindex(all_dates).fillna(False)]
    start_month = pd.Timestamp("2021-01-01")
    end_month = real_dates[-1]

    months = pd.date_range(start_month, end_month, freq="MS")

    rows = []
    for m_start in months:
        m_end = m_start + pd.offsets.MonthEnd(0)
        sim_dates = real_dates[(real_dates >= m_start) & (real_dates <= m_end)]
        if len(sim_dates) < 5:
            continue

        holdings = 3
        result_new = simulate(score_full, returns_full, close, symbols, sim_dates, holdings, config)
        result_old = simulate_old(score_full, returns_full, close, symbols, sim_dates, holdings, config)

        strat_new = float((1 + result_new["net_return"]).prod() - 1)
        strat_old = float((1 + result_old["net_return"]).prod() - 1)
        bench_ret = close[config.benchmark].reindex(sim_dates).pct_change().fillna(0.0)
        bench_total = float((1 + bench_ret).prod() - 1)

        rows.append({
            "month": m_start.strftime("%Y-%m"),
            "strategy_new": strat_new,
            "strategy_old": strat_old,
            "benchmark": bench_total,
            "excess_new": strat_new - bench_total,
            "excess_old": strat_old - bench_total,
        })

    df = pd.DataFrame(rows)

    print(f"\n{'='*90}")
    print(f"{'月份':<10} {'新策略':>10} {'旧策略':>10} {'大盘':>10} {'新超额':>10} {'旧超额':>10}")
    print(f"{'-'*90}")
    for _, r in df.iterrows():
        print(f"{r['month']:<10} {r['strategy_new']:>+9.2%} {r['strategy_old']:>+9.2%} "
              f"{r['benchmark']:>+9.2%} {r['excess_new']:>+9.2%} {r['excess_old']:>+9.2%}")

    print(f"\n{'='*90}")
    print("汇总统计对比")
    print(f"{'='*90}")

    n = len(df)
    win_new = int((df["excess_new"] > 0).sum())
    win_old = int((df["excess_old"] > 0).sum())

    pos_new = df.loc[df["excess_new"] > 0, "excess_new"]
    neg_new = df.loc[df["excess_new"] < 0, "excess_new"]
    pos_old = df.loc[df["excess_old"] > 0, "excess_old"]
    neg_old = df.loc[df["excess_old"] < 0, "excess_old"]

    odds_new = pos_new.mean() / abs(neg_new.mean()) if len(neg_new) else float("nan")
    odds_old = pos_old.mean() / abs(neg_old.mean()) if len(neg_old) else float("nan")

    total_new = float((1 + df["strategy_new"]).prod() - 1)
    total_old = float((1 + df["strategy_old"]).prod() - 1)
    total_bench = float((1 + df["benchmark"]).prod() - 1)

    print(f"\n  {'指标':<24} {'新版(A+B)':>14} {'旧版':>14}")
    print(f"  {'-'*54}")
    print(f"  {'月度胜率':<24} {f'{win_new}/{n}={win_new/n:.1%}':>14} {f'{win_old}/{n}={win_old/n:.1%}':>14}")
    print(f"  {'月均超额':<24} {df['excess_new'].mean():>+13.2%} {df['excess_old'].mean():>+13.2%}")
    print(f"  {'赢时平均超额':<24} {pos_new.mean():>+13.2%} {pos_old.mean():>+13.2%}")
    print(f"  {'输时平均超额':<24} {neg_new.mean():>+13.2%} {neg_old.mean():>+13.2%}")
    print(f"  {'赔率比(赢/|输|)':<24} {odds_new:>14.2f} {odds_old:>14.2f}")
    print(f"  {'最差单月超额':<24} {df['excess_new'].min():>+13.2%} {df['excess_old'].min():>+13.2%}")
    print(f"  {'累计策略收益':<24} {total_new:>+13.2%} {total_old:>+13.2%}")
    print(f"  {'累计大盘收益':<24} {total_bench:>+13.2%} {'':>14}")

    # 找出熊转牛拐点月份(踏空对比) — 用大盘单月>5%来定义
    reversal_months = df[df["benchmark"] > 0.05]
    print(f"\n  === 熊转牛/急涨月份踏空对比 (大盘单月涨幅>5%, 共{len(reversal_months)}个月) ===")
    if len(reversal_months) > 0:
        print(f"  {'月份':<10} {'大盘':>10} {'新策略':>10} {'旧策略':>10} {'新踏空':>10} {'旧踏空':>10}")
        for _, r in reversal_months.iterrows():
            print(f"  {r['month']:<10} {r['benchmark']:>+9.2%} {r['strategy_new']:>+9.2%} {r['strategy_old']:>+9.2%} "
                  f"{r['excess_new']:>+9.2%} {r['excess_old']:>+9.2%}")
        print(f"\n  平均踏空: 新版 {reversal_months['excess_new'].mean():+.2%}  vs  旧版 {reversal_months['excess_old'].mean():+.2%}")


if __name__ == "__main__":
    main()
