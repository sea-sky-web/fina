"""
高频行业轮动策略 — V6

相对 V4 唯一改动（用户选择方向：不再调仓位/风控，改动因子本身，加入资金流/成交量因子）：

    在"动量 + 相对强度"双因子基础上加入第三个因子——成交额放量确认：
        volume_growth(t,i) = MA(amount,10)/MA(amount,30) - 1
        volume_z(t,i)      = CrossSectionalZScore(volume_growth(t,i))
    用于区分"放量突破"（更可信）和"缩量假突破"（动量因子容易被这类噪音带偏）。

    score(t,i) = 0.35 * momentum_z + 0.15 * volume_z + 0.5 * relstrength_rank
    （相对 V4 的 0.5*momentum_z + 0.5*relstrength_rank，从动量权重里切出0.15给新因子，
    相对强度权重不变，只做单变量对照）。

V4 的其余机制（缓冲区滞后换仓、固定双周期集成动量、个股止损 -8% + 5日冷却、等权持仓）
保持不变。
"""

from __future__ import annotations

import json
import time
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

# V6: 成交量放量因子
VOLUME_SHORT_WINDOW = 10
VOLUME_LONG_WINDOW = 30
WEIGHT_MOMENTUM = 0.35
WEIGHT_VOLUME = 0.15
WEIGHT_RELSTRENGTH = 0.50


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    raw = pd.read_parquet(DATA_PATH)
    raw["date"] = pd.to_datetime(raw["date"])
    close = raw.pivot(index="date", columns="symbol", values="close").sort_index()
    amount = raw.pivot(index="date", columns="symbol", values="amount").sort_index()
    close = close.ffill(limit=2)
    amount = amount.ffill(limit=2)
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


def compute_scores_full(close: pd.DataFrame, amount: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    mom_components = []
    for L in MOMENTUM_LOOKBACK_SET:
        ret = close[symbols].pct_change(L)
        mom_components.append(vectorized_zscore(ret))
    mom_z = sum(mom_components) / len(mom_components)

    bench_ret_long = close[BENCHMARK].pct_change(REL_STRENGTH_LOOKBACK)
    ret_long = close[symbols].pct_change(REL_STRENGTH_LOOKBACK)
    excess_long = ret_long.sub(bench_ret_long, axis=0)
    rel_rank = vectorized_pct_rank(excess_long)

    volume_growth = (
        amount[symbols].rolling(VOLUME_SHORT_WINDOW).mean()
        / amount[symbols].rolling(VOLUME_LONG_WINDOW).mean()
        - 1
    )
    volume_z = vectorized_zscore(volume_growth)

    score = WEIGHT_MOMENTUM * mom_z + WEIGHT_VOLUME * volume_z + WEIGHT_RELSTRENGTH * rel_rank
    score[excess_long.isna() | volume_growth.isna()] = np.nan
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


def target_weights_from_symbols(final_set: list[str], symbols: list[str], holdings: int) -> pd.Series:
    weights = pd.Series(0.0, index=symbols)
    if not final_set:
        return weights
    per_weight = min(1.0 / len(final_set), MAX_SYMBOL_WEIGHT)
    weights.loc[final_set] = per_weight
    return weights


def simulate(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    close_full: pd.DataFrame,
    symbols: list[str],
    dates: pd.DatetimeIndex,
    holdings: int,
    cost_rate_one_side: float = COST_RATE_ONE_SIDE,
) -> pd.DataFrame:
    score = score_full.reindex(dates)
    returns = returns_full.reindex(dates)
    prices = close_full.reindex(dates)

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

        target = target_weights_from_symbols(final_set, symbols, holdings)

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
    symbols: list[str],
    train_dates: pd.DatetimeIndex,
) -> tuple[int, float]:
    best = (PARAM_GRID_K[0], -np.inf)
    for K in PARAM_GRID_K:
        sim = simulate(score_full, returns_full, close_full, symbols, train_dates, K)
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


def run_walk_forward(close: pd.DataFrame, amount: pd.DataFrame, symbols: list[str]) -> dict:
    t0 = time.time()
    score_full = compute_scores_full(close, amount, symbols)
    returns_full = close[symbols].pct_change()
    print(f"[precompute] score computed in {time.time()-t0:.1f}s")

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
        best_K, train_obj = grid_search_train(score_full, returns_full, close, symbols, train_dates)
        test_sim = simulate(score_full, returns_full, close, symbols, test_dates, best_K)
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
        "avg_daily_turnover": avg_turnover,
        "total_stop_loss_events": total_stop_loss_events,
    }


def cost_erosion_test(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    close_full: pd.DataFrame,
    symbols: list[str],
    all_dates: pd.DatetimeIndex,
    windows_meta: list[dict],
) -> dict:
    results = {}
    for cost in [0.0, 0.0005, 0.00075, 0.001]:
        spliced = []
        for w in windows_meta:
            test_dates = all_dates[(all_dates >= w["test_start"]) & (all_dates <= w["test_end"])]
            sim = simulate(score_full, returns_full, close_full, symbols, test_dates, w["best_K"], cost_rate_one_side=cost)
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

    result = run_walk_forward(close, amount, symbols)
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
    cost_results = cost_erosion_test(result["score_full"], result["returns_full"], close, symbols, all_dates, windows_for_cost)

    summary = {
        "version": "V6",
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

    print("\n=== SUMMARY V6 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    output_dir = Path("/Users/ster/Desktop/fina/artifacts/backtest_v6")
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(windows).to_csv(output_dir / "windows.csv", index=False)
    spliced.to_csv(output_dir / "spliced_returns.csv")
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved detail to {output_dir}")


if __name__ == "__main__":
    main()
