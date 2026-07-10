"""
高频行业轮动策略 — V3

相对 V2 唯一改动（对应 V2 诊断报告里最突出的问题：最大回撤 -38% 仍是目标 3 倍多、
连续亏损窗口反而从 6 升到 7，说明策略在下跌/震荡市中缺少仓位控制）：

    接入仓库已有的市场状态识别 `app.risk.regime.detect_market_regime()` 同款逻辑
    （基准 MA20/MA60 趋势分 + 20 日年化波动率 + 120 日回撤，三态 risk_off/neutral/risk_on
    对应目标仓位 45%/75%/95%），把组合总仓位按当日市场状态动态缩放——risk_off 时只用
    45% 仓位，其余留现金，而不是像 V2 一样"有信号就用满 K 个名额"。

    出于性能考虑本文件用向量化 rolling 计算复刻了 detect_market_regime 的精确公式
    （避免在 73*4 组网格搜索里对每一天调用一次帯 pivot_table 的原函数），阈值和输出完全一致，
    仅做时点安全（point-in-time，只用截止当日的历史数据，不引入未来信息）。

V2 的两个改动（缓冲区滞后换仓 + 固定双周期集成动量）保持不变，便于对照。
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

# V3: 市场状态阈值，与 app.risk.regime.detect_market_regime 完全一致
REGIME_SHORT_MA = 20
REGIME_LONG_MA = 60
REGIME_DD_WINDOW = 120
REGIME_VOL_WINDOW = 20
RISK_OFF_DD = -0.12
RISK_OFF_TREND = -0.02
RISK_OFF_VOL = 0.35
RISK_ON_TREND = 0.02
RISK_ON_DD = -0.08
RISK_ON_VOL = 0.28
EXPOSURE_RISK_OFF = 0.45
EXPOSURE_NEUTRAL = 0.75
EXPOSURE_RISK_ON = 0.95


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


def compute_regime_exposure(close: pd.DataFrame) -> pd.Series:
    """Point-in-time replica of app.risk.regime.detect_market_regime, vectorized."""
    series = close[BENCHMARK].dropna()
    short_ma = series.rolling(REGIME_SHORT_MA).mean()
    long_ma = series.rolling(REGIME_LONG_MA).mean()
    trend_score = short_ma / long_ma - 1

    recent_high = series.rolling(REGIME_DD_WINDOW, min_periods=1).max()
    drawdown = series / recent_high - 1

    returns = series.pct_change()
    volatility = returns.rolling(REGIME_VOL_WINDOW).std(ddof=0) * sqrt(TRADING_DAYS_PER_YEAR)

    exposure = pd.Series(EXPOSURE_NEUTRAL, index=series.index)
    risk_off_mask = (drawdown <= RISK_OFF_DD) | (trend_score < RISK_OFF_TREND) | (volatility >= RISK_OFF_VOL)
    risk_on_mask = (trend_score >= RISK_ON_TREND) & (drawdown > RISK_ON_DD) & (volatility < RISK_ON_VOL)
    exposure[risk_on_mask] = EXPOSURE_RISK_ON
    exposure[risk_off_mask] = EXPOSURE_RISK_OFF  # risk_off takes precedence, matches original if/elif order

    insufficient_history = long_ma.isna() | volatility.isna()
    exposure[insufficient_history] = EXPOSURE_NEUTRAL
    return exposure.reindex(close.index).ffill().fillna(EXPOSURE_NEUTRAL)


def target_weights_hysteresis(
    score_row: pd.Series, current_weights: pd.Series, holdings: int, exposure: float, buffer: int = HYSTERESIS_BUFFER
) -> pd.Series:
    candidates = score_row.dropna()
    positive = candidates[candidates > 0]
    ranked = positive.sort_values(ascending=False)

    # 持仓判定基于"未缩放前的名义仓位"是否存在，用原始权重符号即可，exposure 缩放不改变排名成员
    currently_held = set(current_weights[current_weights > 0].index)
    top_k_buffer = set(ranked.head(holdings + buffer).index)

    keep_candidates = currently_held & top_k_buffer
    keep_ranked = ranked[ranked.index.isin(keep_candidates)]
    keep_final = list(keep_ranked.head(holdings).index)

    open_slots = holdings - len(keep_final)
    new_candidates = [s for s in ranked.index if s not in keep_final]
    new_adds = new_candidates[: max(open_slots, 0)]
    final_set = keep_final + new_adds

    weights = pd.Series(0.0, index=score_row.index)
    if not final_set:
        return weights
    per_weight = min(1.0 / len(final_set), MAX_SYMBOL_WEIGHT)
    weights.loc[final_set] = per_weight * exposure
    return weights


def simulate(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    exposure_full: pd.Series,
    symbols: list[str],
    dates: pd.DatetimeIndex,
    holdings: int,
    cost_rate_one_side: float = COST_RATE_ONE_SIDE,
) -> pd.DataFrame:
    score = score_full.reindex(dates)
    returns = returns_full.reindex(dates)
    exposure = exposure_full.reindex(dates).fillna(EXPOSURE_NEUTRAL)

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
            target = target_weights_hysteresis(row_score, current_weights, holdings, float(exposure.loc[d]))

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
                "exposure": float(exposure.loc[d]),
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
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    exposure_full: pd.Series,
    symbols: list[str],
    train_dates: pd.DatetimeIndex,
) -> tuple[int, float]:
    best = (PARAM_GRID_K[0], -np.inf)
    for K in PARAM_GRID_K:
        sim = simulate(score_full, returns_full, exposure_full, symbols, train_dates, K)
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
    exposure_full = compute_regime_exposure(close)
    print(f"[precompute] score+regime computed in {time.time()-t0:.1f}s")
    print(f"[regime] exposure distribution:\n{exposure_full.value_counts()}")

    all_dates = close.dropna(how="all").index
    all_dates = all_dates[all_dates.isin(close[symbols].dropna(how="all").index)]
    windows = build_windows(all_dates)
    print(f"[walk_forward] total windows: {len(windows)}")

    window_records = []
    spliced_returns = []
    all_turnovers = []

    for i, (train_dates, test_dates) in enumerate(windows):
        t1 = time.time()
        best_K, train_obj = grid_search_train(score_full, returns_full, exposure_full, symbols, train_dates)
        test_sim = simulate(score_full, returns_full, exposure_full, symbols, test_dates, best_K)
        test_ret = test_sim["net_return"] if not test_sim.empty else pd.Series(dtype=float)
        if not test_sim.empty:
            all_turnovers.append(test_sim["turnover"])

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
        "exposure_full": exposure_full,
        "avg_daily_turnover": avg_turnover,
    }


def cost_erosion_test(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    exposure_full: pd.Series,
    symbols: list[str],
    all_dates: pd.DatetimeIndex,
    windows_meta: list[dict],
) -> dict:
    results = {}
    for cost in [0.0, 0.0005, 0.00075, 0.001]:
        spliced = []
        for w in windows_meta:
            test_dates = all_dates[(all_dates >= w["test_start"]) & (all_dates <= w["test_end"])]
            sim = simulate(score_full, returns_full, exposure_full, symbols, test_dates, w["best_K"], cost_rate_one_side=cost)
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
        result["score_full"], result["returns_full"], result["exposure_full"], symbols, all_dates, windows_for_cost
    )

    summary = {
        "version": "V3",
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
        "cost_erosion": cost_results,
    }

    print("\n=== SUMMARY V3 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    output_dir = Path("/Users/ster/Desktop/fina/artifacts/backtest_v3")
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(windows).to_csv(output_dir / "windows.csv", index=False)
    spliced.to_csv(output_dir / "spliced_returns.csv")
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved detail to {output_dir}")


if __name__ == "__main__":
    main()
