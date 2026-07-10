"""
高频行业轮动策略 — V5

相对 V4 唯一改动：把等权持仓改成波动率倒数加权（inverse-volatility weighting）。
    - 总投资预算与 V4 等权方案完全一致（即 n 只持仓时预算仍是
      n * min(1/n, MAX_SYMBOL_WEIGHT)），只改变预算在 n 只标的间的分配方式：
      20 日年化波动率越高的标的分配权重越小。
    - 单只权重上限依然是 20%，超限部分用瀑布式（waterfall）重新分配给未超限的持仓，
      迭代到没有人超限为止。

延续 V4 的诊断结论（个股层面精细化风险控制比组合层面整体缩放有效）：把风险控制从
"止损二元开关"进一步细化到"持仓权重连续调节"。

V4 的其余机制（缓冲区滞后换仓、固定双周期集成动量、个股止损 -8% + 5日冷却）保持不变。
"""

from __future__ import annotations

import json
import time
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd

DATA_PATH = Path("/Users/ster/Desktop/fina/data/research/etf_daily_backtest.parquet")
BENCHMARK = "510300.SH"
COST_RATE_ONE_SIDE = 0.00075
MAX_SYMBOL_WEIGHT = 0.20
MAX_DAILY_TURNOVER = 0.80
CIRCUIT_BREAKER_DAILY_LOSS = -0.03
TRAIN_TRADING_DAYS = 500
TEST_TRADING_DAYS = 42
STEP_TRADING_DAYS = 21
TRADING_DAYS_PER_YEAR = 252

MOMENTUM_LOOKBACK_SET = [10, 20]
REL_STRENGTH_LOOKBACK = 60
HYSTERESIS_BUFFER = 2
PARAM_GRID_K = [3, 4, 5, 6]

STOP_LOSS_THRESHOLD = -0.08
COOLDOWN_DAYS = 5

# V5: 波动率倒数加权
VOL_LOOKBACK = 20


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    raw = pd.read_parquet(DATA_PATH)
    raw["date"] = pd.to_datetime(raw["date"])
    close = raw.pivot(index="date", columns="symbol", values="close").sort_index()
    amount = raw.pivot(index="date", columns="symbol", values="amount").sort_index()
    close = close.ffill(limit=2)
    symbols = [c for c in close.columns if c != BENCHMARK]
    return close, amount, symbols


def liquidity_filter(amount: pd.DataFrame, symbols: list[str], min_avg_amount: float = 5.0e7) -> list[str]:
    avg_amount = amount[symbols].mean()
    kept = [s for s in symbols if avg_amount.get(s, 0) >= min_avg_amount]
    dropped = sorted(set(symbols) - set(kept))
    if dropped:
        print(f"[liquidity_filter] dropped low-liquidity symbols: {dropped}")
    return kept


def vectorized_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    mean = frame.mean(axis=1)
    std = frame.std(axis=1, ddof=0).replace(0, np.nan)
    z = frame.sub(mean, axis=0).div(std, axis=0)
    return z.fillna(0.0)


def vectorized_pct_rank(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rank(axis=1, pct=True).fillna(0.5)


def compute_scores_full(close: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    mom_components = []
    for L in MOMENTUM_LOOKBACK_SET:
        ret = close[symbols].pct_change(L)
        mom_components.append(vectorized_zscore(ret))
    mom_z = sum(mom_components) / len(mom_components)

    bench_ret_long = close[BENCHMARK].pct_change(REL_STRENGTH_LOOKBACK)
    ret_long = close[symbols].pct_change(REL_STRENGTH_LOOKBACK)
    excess_long = ret_long.sub(bench_ret_long, axis=0)
    rel_rank = vectorized_pct_rank(excess_long)

    score = 0.5 * mom_z + 0.5 * rel_rank
    score[excess_long.isna()] = np.nan
    return score


def target_symbols_hysteresis(
    score_row: pd.Series,
    current_weights: pd.Series,
    holdings: int,
    stopped_out: set[str],
    cooldown: set[str],
    buffer: int = HYSTERESIS_BUFFER,
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


def allocate_inverse_vol_weights(final_set: list[str], vol_row: pd.Series, cap: float = MAX_SYMBOL_WEIGHT) -> dict[str, float]:
    if not final_set:
        return {}
    n = len(final_set)
    total_budget = n * min(1.0 / n, cap)

    vols = {}
    valid = []
    for s in final_set:
        v = vol_row.get(s, np.nan)
        if pd.notna(v) and v > 0:
            vols[s] = v
            valid.append(v)
    fallback = float(np.median(valid)) if valid else 1.0
    for s in final_set:
        if s not in vols:
            vols[s] = fallback

    inv = {s: 1.0 / vols[s] for s in final_set}
    remaining = set(final_set)
    remaining_budget = total_budget
    weights: dict[str, float] = {}

    for _ in range(n + 1):
        if not remaining:
            break
        inv_sum = sum(inv[s] for s in remaining)
        if inv_sum <= 0:
            share = remaining_budget / len(remaining)
            for s in remaining:
                weights[s] = min(share, cap)
            break
        proposed = {s: remaining_budget * inv[s] / inv_sum for s in remaining}
        over_cap = [s for s, w in proposed.items() if w > cap + 1e-9]
        if not over_cap:
            weights.update(proposed)
            break
        for s in over_cap:
            weights[s] = cap
            remaining_budget -= cap
            remaining.discard(s)
    return weights


def simulate(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    close_full: pd.DataFrame,
    vol_full: pd.DataFrame,
    symbols: list[str],
    dates: pd.DatetimeIndex,
    holdings: int,
    cost_rate_one_side: float = COST_RATE_ONE_SIDE,
) -> pd.DataFrame:
    score = score_full.reindex(dates)
    returns = returns_full.reindex(dates)
    prices = close_full.reindex(dates)
    vols = vol_full.reindex(dates)

    current_weights = pd.Series(0.0, index=symbols)
    entry_price: dict[str, float] = {}
    cooldown_until: dict[str, pd.Timestamp] = {}
    paused_until: pd.Timestamp | None = None
    records = []
    stop_loss_events = 0

    for d in dates:
        day_price = prices.loc[d].reindex(symbols)
        day_returns = returns.loc[d].reindex(symbols).fillna(0.0)
        gross_return = float((current_weights * day_returns).sum())

        cooldown_active = {s for s, until in cooldown_until.items() if until >= d}

        stopped_out: set[str] = set()
        for sym in list(current_weights[current_weights > 0].index):
            ep = entry_price.get(sym)
            price_now = day_price.get(sym)
            if ep is None or pd.isna(price_now) or ep == 0:
                continue
            ret_since_entry = price_now / ep - 1
            if ret_since_entry <= STOP_LOSS_THRESHOLD:
                stopped_out.add(sym)
                cooldown_until[sym] = d + pd.tseries.offsets.BDay(COOLDOWN_DAYS)
                stop_loss_events += 1

        if paused_until is not None and d <= paused_until:
            final_set = [s for s in current_weights[current_weights > 0].index if s not in stopped_out]
        else:
            row_score = score.loc[d].reindex(symbols)
            final_set = target_symbols_hysteresis(
                row_score, current_weights, holdings, stopped_out, cooldown_active
            )

        day_vol = vols.loc[d].reindex(symbols)
        alloc = allocate_inverse_vol_weights(final_set, day_vol)
        target = pd.Series(0.0, index=symbols)
        for s, w in alloc.items():
            target[s] = w

        delta = target - current_weights
        planned_turnover = float(delta.abs().sum())
        if planned_turnover > MAX_DAILY_TURNOVER and planned_turnover > 0:
            scale = MAX_DAILY_TURNOVER / planned_turnover
            target = current_weights + delta * scale
            planned_turnover = MAX_DAILY_TURNOVER

        cost = planned_turnover * cost_rate_one_side
        net_return = gross_return - cost

        if net_return <= CIRCUIT_BREAKER_DAILY_LOSS:
            paused_until = d + pd.tseries.offsets.BDay(1)

        for sym in symbols:
            was_held = current_weights.get(sym, 0.0) > 0
            now_held = target.get(sym, 0.0) > 0
            if now_held and not was_held:
                entry_price[sym] = day_price.get(sym, np.nan)
            elif not now_held and was_held:
                entry_price.pop(sym, None)

        current_weights = target
        records.append(
            {
                "date": d,
                "gross_return": gross_return,
                "cost": cost,
                "net_return": net_return,
                "turnover": planned_turnover,
                "n_holdings": int((current_weights > 0).sum()),
                "stop_loss_triggered": len(stopped_out),
            }
        )

    result = pd.DataFrame(records).set_index("date")
    result.attrs["stop_loss_events"] = stop_loss_events
    return result


def annualized_return(daily_returns: pd.Series) -> float:
    if daily_returns.empty:
        return 0.0
    cumulative = float((1 + daily_returns).prod())
    n = len(daily_returns)
    if n == 0 or cumulative <= 0:
        return -1.0
    return cumulative ** (TRADING_DAYS_PER_YEAR / n) - 1


def max_drawdown(daily_returns: pd.Series) -> float:
    if daily_returns.empty:
        return 0.0
    equity = (1 + daily_returns).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1
    return float(dd.min())


def sharpe_ratio(daily_returns: pd.Series) -> float:
    if daily_returns.empty or daily_returns.std(ddof=0) == 0:
        return 0.0
    return float(daily_returns.mean() / daily_returns.std(ddof=0) * np.sqrt(TRADING_DAYS_PER_YEAR))


def calmar_ratio(daily_returns: pd.Series) -> float:
    mdd = max_drawdown(daily_returns)
    if mdd == 0:
        return 0.0
    return annualized_return(daily_returns) / abs(mdd)


def grid_search_train(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    close_full: pd.DataFrame,
    vol_full: pd.DataFrame,
    symbols: list[str],
    train_dates: pd.DatetimeIndex,
) -> tuple[int, float]:
    best = (PARAM_GRID_K[0], -np.inf)
    for K in PARAM_GRID_K:
        sim = simulate(score_full, returns_full, close_full, vol_full, symbols, train_dates, K)
        if sim.empty:
            continue
        r = sim["net_return"]
        objective = sharpe_ratio(r) + calmar_ratio(r)
        if objective > best[1]:
            best = (K, objective)
    return best


def build_windows(all_dates: pd.DatetimeIndex) -> list[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    windows = []
    start_idx = 0
    while True:
        train_start = start_idx
        train_end = train_start + TRAIN_TRADING_DAYS
        test_end = train_end + TEST_TRADING_DAYS
        if test_end > len(all_dates):
            break
        train_dates = all_dates[train_start:train_end]
        test_dates = all_dates[train_end:test_end]
        windows.append((train_dates, test_dates))
        start_idx += STEP_TRADING_DAYS
    return windows


def benchmark_returns(close: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    ret = close[BENCHMARK].pct_change().reindex(dates)
    return ret.fillna(0.0)


def run_walk_forward(close: pd.DataFrame, symbols: list[str]) -> dict:
    t0 = time.time()
    score_full = compute_scores_full(close, symbols)
    returns_full = close[symbols].pct_change()
    vol_full = returns_full.rolling(VOL_LOOKBACK).std(ddof=0) * sqrt(TRADING_DAYS_PER_YEAR)
    print(f"[precompute] score+vol computed in {time.time()-t0:.1f}s")

    all_dates = close.dropna(how="all").index
    all_dates = all_dates[all_dates.isin(close[symbols].dropna(how="all").index)]
    windows = build_windows(all_dates)
    print(f"[walk_forward] total windows: {len(windows)}")

    window_records = []
    spliced_returns = []
    all_turnovers = []
    total_stop_loss_events = 0

    for i, (train_dates, test_dates) in enumerate(windows):
        t1 = time.time()
        best_K, train_obj = grid_search_train(score_full, returns_full, close, vol_full, symbols, train_dates)
        test_sim = simulate(score_full, returns_full, close, vol_full, symbols, test_dates, best_K)
        test_ret = test_sim["net_return"] if not test_sim.empty else pd.Series(dtype=float)
        if not test_sim.empty:
            all_turnovers.append(test_sim["turnover"])
            total_stop_loss_events += test_sim.attrs.get("stop_loss_events", 0)

        bench_ret = benchmark_returns(close, test_dates)

        window_return = float((1 + test_ret).prod() - 1) if not test_ret.empty else 0.0
        bench_window_return = float((1 + bench_ret).prod() - 1)
        window_mdd = max_drawdown(test_ret)
        window_sharpe = sharpe_ratio(test_ret)

        step_dates = test_dates[:STEP_TRADING_DAYS]
        spliced_returns.append(test_ret.reindex(step_dates).fillna(0.0))

        window_records.append(
            {
                "window": i + 1,
                "train_start": str(train_dates[0].date()),
                "train_end": str(train_dates[-1].date()),
                "test_start": str(test_dates[0].date()),
                "test_end": str(test_dates[-1].date()),
                "best_K": best_K,
                "train_objective": round(train_obj, 4),
                "window_return": round(window_return, 4),
                "bench_window_return": round(bench_window_return, 4),
                "excess_vs_bench": round(window_return - bench_window_return, 4),
                "window_max_drawdown": round(window_mdd, 4),
                "window_sharpe": round(window_sharpe, 4),
            }
        )
        print(
            f"  W{i+1:02d} [{test_dates[0].date()}~{test_dates[-1].date()}] "
            f"K={best_K} ret={window_return:+.2%} bench={bench_window_return:+.2%} "
            f"excess={window_return - bench_window_return:+.2%} mdd={window_mdd:.2%} "
            f"({time.time()-t1:.1f}s)"
        )

    spliced = pd.concat(spliced_returns).sort_index()
    spliced = spliced[~spliced.index.duplicated(keep="first")]
    avg_turnover = float(pd.concat(all_turnovers).mean()) if all_turnovers else 0.0

    return {
        "windows": window_records,
        "spliced_returns": spliced,
        "score_full": score_full,
        "returns_full": returns_full,
        "vol_full": vol_full,
        "avg_daily_turnover": avg_turnover,
        "total_stop_loss_events": total_stop_loss_events,
    }


def cost_erosion_test(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    close_full: pd.DataFrame,
    vol_full: pd.DataFrame,
    symbols: list[str],
    all_dates: pd.DatetimeIndex,
    windows_meta: list[dict],
) -> dict:
    results = {}
    for cost in [0.0, 0.0005, 0.00075, 0.001]:
        spliced = []
        for w in windows_meta:
            test_dates = all_dates[(all_dates >= w["test_start"]) & (all_dates <= w["test_end"])]
            sim = simulate(score_full, returns_full, close_full, vol_full, symbols, test_dates, w["best_K"], cost_rate_one_side=cost)
            if sim.empty:
                continue
            step_dates = test_dates[:STEP_TRADING_DAYS]
            spliced.append(sim["net_return"].reindex(step_dates).fillna(0.0))
        if not spliced:
            continue
        full = pd.concat(spliced).sort_index()
        full = full[~full.index.duplicated(keep="first")]
        total_return = float((1 + full).prod() - 1)
        results[f"round_trip_{cost*2*10000:.1f}bps"] = round(total_return, 4)
    return results


def main() -> None:
    close, amount, symbols = load_data()
    symbols = liquidity_filter(amount, symbols)
    print(f"[universe] {len(symbols)} symbols after liquidity filter: {symbols}")

    result = run_walk_forward(close, symbols)
    windows = result["windows"]
    spliced = result["spliced_returns"]

    ann_ret = annualized_return(spliced)
    mdd = max_drawdown(spliced)
    sharpe = sharpe_ratio(spliced)
    calmar = calmar_ratio(spliced)

    bench_full = benchmark_returns(close, spliced.index)
    bench_ann_ret = annualized_return(bench_full)

    win_rate = float(np.mean([1.0 if w["excess_vs_bench"] > 0 else 0.0 for w in windows]))
    window_returns = [w["window_return"] for w in windows]
    window_std = float(np.std(window_returns))
    worst_window = min(window_returns)

    Ks = [w["best_K"] for w in windows]
    cv_K = float(np.std(Ks) / np.mean(Ks)) if np.mean(Ks) != 0 else 0.0

    consecutive_losses = 0
    max_consecutive_losses = 0
    for w in windows:
        if w["window_return"] < 0:
            consecutive_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        else:
            consecutive_losses = 0

    all_dates = close.dropna(how="all").index
    all_dates = all_dates[all_dates.isin(close[symbols].dropna(how="all").index)]
    windows_for_cost = [
        {"test_start": pd.Timestamp(w["test_start"]), "test_end": pd.Timestamp(w["test_end"]), "best_K": w["best_K"]}
        for w in windows
    ]
    cost_results = cost_erosion_test(
        result["score_full"], result["returns_full"], close, result["vol_full"], symbols, all_dates, windows_for_cost
    )

    summary = {
        "version": "V5",
        "n_windows": len(windows),
        "spliced_start": str(spliced.index[0].date()),
        "spliced_end": str(spliced.index[-1].date()),
        "annualized_return": round(ann_ret, 4),
        "benchmark_annualized_return": round(bench_ann_ret, 4),
        "max_drawdown": round(mdd, 4),
        "sharpe": round(sharpe, 4),
        "calmar": round(calmar, 4),
        "window_win_rate_vs_benchmark": round(win_rate, 4),
        "window_return_std": round(window_std, 4),
        "worst_single_window_return": round(worst_window, 4),
        "param_K_sequence": Ks,
        "param_cv_K": round(cv_K, 4),
        "max_consecutive_losing_windows": max_consecutive_losses,
        "avg_daily_turnover": round(result["avg_daily_turnover"], 4),
        "total_stop_loss_events": result["total_stop_loss_events"],
        "cost_erosion": cost_results,
    }

    print("\n=== SUMMARY V5 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    output_dir = Path("/Users/ster/Desktop/fina/artifacts/backtest_v5")
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(windows).to_csv(output_dir / "windows.csv", index=False)
    spliced.to_csv(output_dir / "spliced_returns.csv")
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved detail to {output_dir}")


if __name__ == "__main__":
    main()
