"""过去一个月每日持仓/损益复盘 — 直接调用真实引擎(已修复A+B),避免逻辑漂移."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

import pandas as pd

from rotation.config import DEFAULT_CONFIG
from rotation.data import load_data, liquidity_filter
from rotation.signals import compute_scores
from rotation.engine import simulate


def main():
    config = DEFAULT_CONFIG
    close, amount, symbols = load_data(config)
    symbols = liquidity_filter(amount, symbols, config)
    day_counts = close[symbols].count()
    symbols = [s for s in symbols if day_counts.get(s, 0) >= config.min_history_days]
    print(f"[universe] {len(symbols)} symbols  |  bull_boost={config.bull_boost}  bear_scale={config.bear_scale}")

    basic_path = ROOT / "data" / "clean" / "etf_basic.parquet"
    name_map = {}
    if basic_path.exists():
        basic = pd.read_parquet(basic_path)
        name_map = dict(zip(basic["symbol"], basic["name"]))

    score_full = compute_scores(close, symbols, amount, config)
    returns_full = close.pct_change(fill_method=None)

    all_dates = close.index.sort_values()
    bench_close_all = close[config.benchmark]
    valid_mask = bench_close_all.pct_change().abs() > 0
    real_dates = all_dates[valid_mask.reindex(all_dates).fillna(False)]

    stale_dates = all_dates[all_dates > real_dates[-1]]
    if len(stale_dates) > 0:
        print(f"[警告] 数据在 {real_dates[-1].date()} 之后为空/未更新, "
              f"忽略 {len(stale_dates)} 个陈旧交易日: {[d.date() for d in stale_dates]}")

    end_date = real_dates[-1]
    start_date = end_date - pd.Timedelta(days=35)
    sim_dates = real_dates[(real_dates >= start_date) & (real_dates <= end_date)]
    print(f"[period] {sim_dates[0].date()} ~ {sim_dates[-1].date()}, {len(sim_dates)} 个有效交易日\n")

    K = config.param_grid_k[1]  # K=3
    result = simulate(
        score_full, returns_full, close, symbols, sim_dates, holdings=K,
        config=config, record_weights=True,
    )

    bench_ret = close[config.benchmark].reindex(sim_dates).pct_change(fill_method=None).fillna(0.0)
    bench_equity = (1 + bench_ret).cumprod()
    strat_equity = (1 + result["net_return"]).cumprod()

    prev_weights_after = {}

    for d in sim_dates:
        row = result.loc[d]
        net_ret = float(row["net_return"])
        b_ret = float(bench_ret.loc[d])
        w_before = row["weights_before"]
        w_after = row["weights_after"]
        contrib = row["contributions"]
        rets = row["returns"]
        regime = float(row["regime_scale"])
        stopped = row["stopped_out"]

        regime_label = {0.5: "熊市(50%)", 0.75: "中性(75%)", 1.0: "牛市(100%)"}.get(regime, f"{regime:.0%}")

        tags = [f"regime={regime_label}"]
        if row["circuit_triggered"]:
            tags.append("熔断触发→权重回退")
        if row["in_dd_cooldown"]:
            tags.append("组合回撤保护")
        if row["use_bench_slot"]:
            tags.append("再入场观察(基准槽位)")
        if stopped:
            tags.append(f"止损×{len(stopped)}: {','.join(stopped)}")

        print(f"{'─'*84}")
        print(f"📅 {d.date()}  策略: {net_ret:+.2%}  大盘: {b_ret:+.2%}  超额: {net_ret - b_ret:+.2%}")
        print(f"   策略净值: {strat_equity.loc[d]:.4f}  大盘净值: {bench_equity.loc[d]:.4f}  "
              f"【{' | '.join(tags)}】")

        held_syms = sorted({s for s, w in w_after.items() if w > 0} | {s for s, w in w_before.items() if w > 0})
        if not held_syms:
            print("   持仓: 空仓")
        else:
            print(f"   {'标的':<12}{'名称':<16}{'权重':>7}{'日收益':>9}{'贡献':>9}  状态")
            for sym in held_syms:
                wb = w_before.get(sym, 0.0)
                wa = w_after.get(sym, 0.0)
                ret = rets.get(sym, 0.0)
                c = contrib.get(sym, 0.0)
                nm = (name_map.get(sym, sym) or sym)[:8]
                if wb == 0 and wa > 0:
                    status = "新买入"
                elif wb > 0 and wa == 0:
                    status = "止损卖出" if sym in stopped else "卖出"
                elif wb > 0 and wa > 0:
                    status = "持有"
                else:
                    status = "-"
                disp_w = wa if wa > 0 else wb
                print(f"   {sym:<12}{nm:<16}{disp_w:>6.0%}{ret:>+8.2%}{c:>+8.2%}  {status}")

        turnover = float(row["turnover"])
        if turnover > 0:
            print(f"   换手率: {turnover:.1%}  交易成本: {float(row['cost']):.4f}")

    total_strat = float(strat_equity.iloc[-1] - 1)
    total_bench = float(bench_equity.iloc[-1] - 1)
    win_days = int((result["net_return"] > bench_ret).sum())

    print(f"\n{'='*84}")
    print(f"{'过去一个月汇总 (已应用方案A去杠杆 + 方案B多信号regime)':^84}")
    print(f"{'='*84}")
    print(f"  累计收益:  策略 {total_strat:+.2%}   大盘 {total_bench:+.2%}   超额 {total_strat - total_bench:+.2%}")
    print(f"  日胜率:    {win_days}/{len(sim_dates)} = {win_days/len(sim_dates):.1%}")
    print(f"  止损触发:  {result['stopped_out'].apply(len).sum()} 次")
    print(f"  熔断触发:  {int(result['circuit_triggered'].sum())} 次")
    print(f"  平均换手率: {result['turnover'].mean():.1%}")
    print(f"  累计交易成本: {result['cost'].sum():.4f}")


if __name__ == "__main__":
    main()
