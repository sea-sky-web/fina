"""最近两周(14个自然日窗口)每日持仓/收益/大盘对比 + 策略描述."""
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

    end_date = real_dates[-1]
    start_date = end_date - pd.Timedelta(days=14)
    # 需要更早的warm-up窗口让entry_price/cooldown/回撤保护状态正确演化
    warmup_start = end_date - pd.Timedelta(days=60)
    warmup_dates = real_dates[(real_dates >= warmup_start) & (real_dates <= end_date)]
    display_dates = real_dates[(real_dates >= start_date) & (real_dates <= end_date)]

    K = config.param_grid_k[1]
    result = simulate(
        score_full, returns_full, close, symbols, warmup_dates, holdings=K,
        config=config, record_weights=True,
    )

    bench_ret = close[config.benchmark].reindex(warmup_dates).pct_change(fill_method=None).fillna(0.0)
    bench_equity_full = (1 + bench_ret).cumprod()
    strat_equity_full = (1 + result["net_return"]).cumprod()

    # 仅展示窗口的基准起点(用于计算窗口内的相对表现)
    base_idx = list(warmup_dates).index(display_dates[0])
    strat_base = strat_equity_full.iloc[base_idx - 1] if base_idx > 0 else 1.0
    bench_base = bench_equity_full.iloc[base_idx - 1] if base_idx > 0 else 1.0

    print(f"展示区间: {display_dates[0].date()} ~ {display_dates[-1].date()}  ({len(display_dates)}个交易日)")
    print(f"(warm-up从{warmup_dates[0].date()}开始模拟,确保止损/冷却/回撤保护状态正确)\n")

    for d in display_dates:
        row = result.loc[d]
        net_ret = float(row["net_return"])
        b_ret = float(bench_ret.loc[d])
        w_before = row["weights_before"]
        w_after = row["weights_after"]
        contrib = row["contributions"]
        rets = row["returns"]
        regime = float(row["regime_scale"])
        stopped = row["stopped_out"]

        regime_label = {0.5: "熊市50%", 0.75: "中性75%", 1.0: "牛市100%"}.get(regime, f"{regime:.0%}")

        held_before = sorted({s for s, w in w_before.items() if w > 0})
        held_after = sorted({s for s, w in w_after.items() if w > 0})
        added = [s for s in held_after if s not in held_before]
        removed = [s for s in held_before if s not in held_after]

        # 策略描述文本
        desc_parts = []
        if row["circuit_triggered"]:
            desc_parts.append("单日亏损触及熔断阈值,回退到调仓前权重,阻止当日进一步操作")
        elif row["in_dd_cooldown"]:
            desc_parts.append("组合回撤保护冷却中,维持空仓/不加仓")
        else:
            desc_parts.append(f"市场判定为{regime_label}")
            if stopped:
                names = "、".join(f"{s}({name_map.get(s,s)})" for s in stopped)
                desc_parts.append(f"个股止损触发: {names}")
            if added:
                names = "、".join(f"{s}({name_map.get(s,s)})" for s in added)
                desc_parts.append(f"新纳入: {names}")
            if removed and not stopped:
                names = "、".join(f"{s}({name_map.get(s,s)})" for s in removed)
                desc_parts.append(f"换出: {names}")
            if row["use_bench_slot"]:
                desc_parts.append("处于再入场观察期,保留基准ETF过渡仓位")
            if not added and not removed:
                desc_parts.append("持仓不变,继续持有")

        print(f"{'─'*90}")
        print(f"📅 {d.date()}  策略日收益: {net_ret:+.2%}   大盘日收益: {b_ret:+.2%}   超额: {net_ret - b_ret:+.2%}")
        print(f"   策略描述: {'; '.join(desc_parts)}")

        if not held_after and not held_before:
            print("   持仓: 空仓")
        else:
            print(f"   {'标的':<12}{'名称':<16}{'权重':>7}{'日收益':>9}{'贡献':>9}")
            display_syms = sorted(set(held_before) | set(held_after))
            for sym in display_syms:
                wb = w_before.get(sym, 0.0)
                wa = w_after.get(sym, 0.0)
                ret = rets.get(sym, 0.0)
                c = contrib.get(sym, 0.0)
                nm = (name_map.get(sym, sym) or sym)[:8]
                disp_w = wa if wa > 0 else wb
                print(f"   {sym:<12}{nm:<16}{disp_w:>6.0%}{ret:>+8.2%}{c:>+8.2%}")

        turnover = float(row["turnover"])
        if turnover > 0:
            print(f"   换手率: {turnover:.1%}  交易成本: {float(row['cost']):.4f}")

    # 窗口汇总
    window_strat = float(strat_equity_full.loc[display_dates[-1]] / strat_base - 1)
    window_bench = float(bench_equity_full.loc[display_dates[-1]] / bench_base - 1)
    win_days = int((result.loc[display_dates, "net_return"] > bench_ret.loc[display_dates]).sum())

    print(f"\n{'='*90}")
    print(f"{'最近两周汇总':^90}")
    print(f"{'='*90}")
    print(f"  累计收益:  策略 {window_strat:+.2%}   大盘 {window_bench:+.2%}   超额 {window_strat - window_bench:+.2%}")
    print(f"  日胜率:    {win_days}/{len(display_dates)} = {win_days/len(display_dates):.1%}")
    print(f"  止损触发:  {result.loc[display_dates, 'stopped_out'].apply(len).sum()} 次")
    print(f"  熔断触发:  {int(result.loc[display_dates, 'circuit_triggered'].sum())} 次")
    print(f"  平均换手率: {result.loc[display_dates, 'turnover'].mean():.1%}")


if __name__ == "__main__":
    main()
