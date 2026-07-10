"""
高频行业轮动策略 — V1 双因子模型 + 滚动 Walk-Forward 回测

信号逻辑：
    momentum_z   = 横截面 z-score( 过去 L 日收益率 )                      -- 短期动量
    relstrength  = 横截面百分位排名( 过去 min(4L, 60) 日相对基准超额收益 )  -- 相对强度
    score        = 0.5 * momentum_z + 0.5 * relstrength

选股：score > 0 的标的中取分数最高的 K 只，等权（单只上限 20%），
      不足 K 只时剩余部分留存现金（空仓）。

参数空间：
    L (动量周期): [3, 5, 10, 20]
    K (持仓数量): [3, 4, 5, 6]

Walk-Forward：
    训练窗口 = 交易日切片下最近 24 个月（约 500 个交易日），网格搜索 (L,K)
               使 训练期内 (Sharpe + Calmar) 最大化。
    测试窗口 = 紧邻训练窗口之后的 2 个月（约 42 个交易日），步长 1 个月（约 21 个交易日）。
    每个测试窗口独立使用该窗口训练出的最优 (L,K) 运行，不使用未来信息。

拼接口径：
    - 窗口级统计（胜率、单窗口最大亏损、参数漂移）使用完整 2 个月测试窗口收益，
      允许相邻窗口重叠（重叠 1 个月），这是常见的滚动评估做法。
    - 全样本外净值曲线为避免重叠重复计入收益，只取每个测试窗口的前 1 个月（步长部分）
      顺序拼接，得到一条不重叠的连续样本外净值曲线。

性能说明：score 只依赖 L，不依赖 K；因此对每个 L 只在全历史上计算一次并缓存，
避免网格搜索时对同一个 L 重复做整段历史的横截面计算。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

DATA_PATH = Path("/Users/ster/Desktop/fina/data/research/etf_daily_backtest.parquet")
BENCHMARK = "510300.SH"
COST_RATE_ONE_SIDE = 0.00075  # 0.075% 单边 -> 买卖合计 0.15%
MAX_SYMBOL_WEIGHT = 0.20
MAX_DAILY_TURNOVER = 0.80
CIRCUIT_BREAKER_DAILY_LOSS = -0.03
TRAIN_TRADING_DAYS = 500  # ~24 个月
TEST_TRADING_DAYS = 42  # ~2 个月
STEP_TRADING_DAYS = 21  # ~1 个月
PARAM_GRID_L = [3, 5, 10, 20]
PARAM_GRID_K = [3, 4, 5, 6]
TRADING_DAYS_PER_YEAR = 252


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


def compute_scores_full(close: pd.DataFrame, symbols: list[str], momentum_lookback: int) -> pd.DataFrame:
    rel_lookback = min(momentum_lookback * 4, 60)
    ret_short = close[symbols].pct_change(momentum_lookback)
    bench_ret_long = close[BENCHMARK].pct_change(rel_lookback)
    ret_long = close[symbols].pct_change(rel_lookback)
    excess_long = ret_long.sub(bench_ret_long, axis=0)

    mom_z = vectorized_zscore(ret_short)
    rel_rank = vectorized_pct_rank(excess_long)
    score = 0.5 * mom_z + 0.5 * rel_rank
    score[ret_short.isna()] = np.nan
    return score


def target_weights_from_scores(score_row: pd.Series, holdings: int) -> pd.Series:
    candidates = score_row.dropna()
    candidates = candidates[candidates > 0].sort_values(ascending=False)
    selected = candidates.head(holdings)
    weights = pd.Series(0.0, index=score_row.index)
    if selected.empty:
        return weights
    per_weight = min(1.0 / holdings, MAX_SYMBOL_WEIGHT)
    weights.loc[selected.index] = per_weight
    return weights


def simulate(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    symbols: list[str],
    dates: pd.DatetimeIndex,
    holdings: int,
    cost_rate_one_side: float = COST_RATE_ONE_SIDE,
) -> pd.DataFrame:
    """Simulate the daily-rebalanced strategy over `dates` using precomputed score/returns."""
    score = score_full.reindex(dates)
    returns = returns_full.reindex(dates)

    current_weights = pd.Series(0.0, index=symbols)
    paused_until: pd.Timestamp | None = None
    records = []

    for d in dates:
        day_returns = returns.loc[d].reindex(symbols).fillna(0.0)
        gross_return = float((current_weights * day_returns).sum())

        if paused_until is not None and d <= paused_until:
            target = current_weights.copy()
        else:
            row_score = score.loc[d].reindex(symbols)
            target = target_weights_from_scores(row_score, holdings)

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

        current_weights = target
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

    return pd.DataFrame(records).set_index("date")


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
    scores_by_L: dict[int, pd.DataFrame],
    returns_full: pd.DataFrame,
    symbols: list[str],
    train_dates: pd.DatetimeIndex,
) -> tuple[int, int, float]:
    best = (PARAM_GRID_L[0], PARAM_GRID_K[0], -np.inf)
    for L in PARAM_GRID_L:
        for K in PARAM_GRID_K:
            sim = simulate(scores_by_L[L], returns_full, symbols, train_dates, K)
            if sim.empty:
                continue
            r = sim["net_return"]
            objective = sharpe_ratio(r) + calmar_ratio(r)
            if objective > best[2]:
                best = (L, K, objective)
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


def equal_weight_pool_returns(close: pd.DataFrame, symbols: list[str], dates: pd.DatetimeIndex) -> pd.Series:
    ret = close[symbols].pct_change().reindex(dates)
    return ret.mean(axis=1).fillna(0.0)


def run_walk_forward(close: pd.DataFrame, symbols: list[str]) -> dict:
    t0 = time.time()
    scores_by_L = {L: compute_scores_full(close, symbols, L) for L in PARAM_GRID_L}
    returns_full = close[symbols].pct_change()
    print(f"[precompute] scores for {len(PARAM_GRID_L)} L values in {time.time()-t0:.1f}s")

    all_dates = close.dropna(how="all").index
    all_dates = all_dates[all_dates.isin(close[symbols].dropna(how="all").index)]
    windows = build_windows(all_dates)
    print(f"[walk_forward] total windows: {len(windows)}")

    window_records = []
    spliced_returns = []

    for i, (train_dates, test_dates) in enumerate(windows):
        t1 = time.time()
        best_L, best_K, train_obj = grid_search_train(scores_by_L, returns_full, symbols, train_dates)
        test_sim = simulate(scores_by_L[best_L], returns_full, symbols, test_dates, best_K)
        test_ret = test_sim["net_return"] if not test_sim.empty else pd.Series(dtype=float)

        bench_ret = benchmark_returns(close, test_dates)
        pool_ret = equal_weight_pool_returns(close, symbols, test_dates)

        window_return = float((1 + test_ret).prod() - 1) if not test_ret.empty else 0.0
        bench_window_return = float((1 + bench_ret).prod() - 1)
        pool_window_return = float((1 + pool_ret).prod() - 1)
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
                "best_L": best_L,
                "best_K": best_K,
                "train_objective": round(train_obj, 4),
                "window_return": round(window_return, 4),
                "bench_window_return": round(bench_window_return, 4),
                "pool_window_return": round(pool_window_return, 4),
                "excess_vs_bench": round(window_return - bench_window_return, 4),
                "window_max_drawdown": round(window_mdd, 4),
                "window_sharpe": round(window_sharpe, 4),
            }
        )
        print(
            f"  W{i+1:02d} [{test_dates[0].date()}~{test_dates[-1].date()}] "
            f"L={best_L} K={best_K} ret={window_return:+.2%} bench={bench_window_return:+.2%} "
            f"excess={window_return - bench_window_return:+.2%} mdd={window_mdd:.2%} "
            f"({time.time()-t1:.1f}s)"
        )

    spliced = pd.concat(spliced_returns).sort_index()
    spliced = spliced[~spliced.index.duplicated(keep="first")]

    return {
        "windows": window_records,
        "spliced_returns": spliced,
        "scores_by_L": scores_by_L,
        "returns_full": returns_full,
    }


def cost_erosion_test(
    scores_by_L: dict[int, pd.DataFrame],
    returns_full: pd.DataFrame,
    symbols: list[str],
    all_dates: pd.DatetimeIndex,
    windows_meta: list[dict],
) -> dict:
    results = {}
    for cost in [0.0, 0.0005, 0.00075, 0.001]:  # one-side rates -> round trip 0, 1‰, 1.5‰, 2‰
        spliced = []
        for w in windows_meta:
            test_dates = all_dates[(all_dates >= w["test_start"]) & (all_dates <= w["test_end"])]
            sim = simulate(scores_by_L[w["best_L"]], returns_full, symbols, test_dates, w["best_K"], cost_rate_one_side=cost)
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

    Ls = [w["best_L"] for w in windows]
    Ks = [w["best_K"] for w in windows]
    cv_L = float(np.std(Ls) / np.mean(Ls)) if np.mean(Ls) != 0 else 0.0
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
        {"test_start": pd.Timestamp(w["test_start"]), "test_end": pd.Timestamp(w["test_end"]), "best_L": w["best_L"], "best_K": w["best_K"]}
        for w in windows
    ]
    cost_results = cost_erosion_test(result["scores_by_L"], result["returns_full"], symbols, all_dates, windows_for_cost)

    summary = {
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
        "param_L_sequence": Ls,
        "param_K_sequence": Ks,
        "param_cv_L": round(cv_L, 4),
        "param_cv_K": round(cv_K, 4),
        "max_consecutive_losing_windows": max_consecutive_losses,
        "cost_erosion": cost_results,
    }

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    output_dir = Path("/Users/ster/Desktop/fina/artifacts/backtest_v1")
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(windows).to_csv(output_dir / "windows.csv", index=False)
    spliced.to_csv(output_dir / "spliced_returns.csv")
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved detail to {output_dir}")


if __name__ == "__main__":
    main()
