"""
高频行业轮动策略 V52 —— 回归趋势强度信号（进攻模式）

灵感来源：BigQuant ETF轮动策略（年化27.15%, Sharpe 1.41）
核心改动：
1. 用 25日回归斜率×R² 替代传统动量z-score
   - slope: 线性回归log(close)的年化斜率 → 趋势方向和速度
   - R²: 拟合优度 → 趋势的"干净程度"
   - signal = slope × R² → 只奖励干净、持续的趋势
2. MA50 趋势过滤: 只考虑价格在50日均线之上的ETF（顺势交易）
3. 进攻配置: K=3, BULL_BOOST=1.33 (牛市满仓), BEAR_SCALE=0.50
4. 保留相对强度因子作为辅助
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
MAX_SYMBOL_WEIGHT = 0.25
MAX_DAILY_TURNOVER = 0.90
CIRCUIT_BREAKER_DAILY_LOSS = -0.03
MIN_TRAIN_DAYS = 250
TEST_TRADING_DAYS = 42
STEP_TRADING_DAYS = 21
EMBARGO_DAYS = 1
TRADING_DAYS_PER_YEAR = 252

REGRESSION_LOOKBACK = 25
REL_STRENGTH_LOOKBACK = 60
MA_FILTER_PERIOD = 50
HYSTERESIS_BUFFER = 3
PARAM_GRID_K = [3]

STOP_LOSS_THRESHOLD = -0.05
COOLDOWN_DAYS = 5


def load_data():
    raw = pd.read_parquet(DATA_PATH)
    raw["date"] = pd.to_datetime(raw["date"])
    close = raw.pivot(index="date", columns="symbol", values="close").sort_index()
    amount = raw.pivot(index="date", columns="symbol", values="amount").sort_index()
    close = close.ffill(limit=2)
    symbols = [c for c in close.columns if c != BENCHMARK]
    return close, amount, symbols


def liquidity_filter(amount, symbols, min_avg_amount=5.0e7):
    avg_amount = amount[symbols].mean()
    kept = [s for s in symbols if avg_amount.get(s, 0) >= min_avg_amount]
    dropped = sorted(set(symbols) - set(kept))
    if dropped:
        print(f"[liquidity_filter] dropped: {dropped}")
    return kept


def restrict_to_common_history(close, symbols):
    valid = close[symbols + [BENCHMARK]].dropna(how="any")
    return valid.index


def vectorized_pct_rank(frame):
    return frame.rank(axis=1, pct=True).fillna(0.5)


def compute_regression_signal(close, symbols, lookback=REGRESSION_LOOKBACK):
    """Compute annualized regression slope × R² for each ETF."""
    log_close = np.log(close[symbols].replace(0, np.nan))
    slope_df = pd.DataFrame(index=close.index, columns=symbols, dtype=float)
    r2_df = pd.DataFrame(index=close.index, columns=symbols, dtype=float)
    
    x = np.arange(lookback, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()
    
    for i in range(lookback, len(close)):
        window = log_close.iloc[i - lookback:i]
        if window.isna().any().any():
            continue
        y = window.values  # shape: (lookback, n_symbols)
        y_mean = y.mean(axis=0)
        
        numerator = ((x - x_mean).reshape(-1, 1) * (y - y_mean)).sum(axis=0)
        slope = numerator / x_var
        
        y_pred = x_mean + slope * (x - x_mean).reshape(-1, 1) + y_mean
        ss_res = ((y - y_pred) ** 2).sum(axis=0)
        ss_tot = ((y - y_mean) ** 2).sum(axis=0)
        r2 = np.where(ss_tot > 0, 1 - ss_res / ss_tot, 0)
        
        annualized_slope = slope * TRADING_DAYS_PER_YEAR
        slope_df.iloc[i] = annualized_slope
        r2_df.iloc[i] = r2
    
    trend_strength = slope_df * r2_df
    return trend_strength.astype(float)


def compute_scores_full(close, symbols):
    trend = compute_regression_signal(close, symbols)
    
    def cross_zscore(frame):
        mean = frame.mean(axis=1)
        std = frame.std(axis=1, ddof=0).replace(0, np.nan)
        return frame.sub(mean, axis=0).div(std, axis=0).fillna(0.0)
    
    trend_z = cross_zscore(trend)
    
    bench_ret_long = close[BENCHMARK].pct_change(REL_STRENGTH_LOOKBACK)
    ret_long = close[symbols].pct_change(REL_STRENGTH_LOOKBACK)
    excess_long = ret_long.sub(bench_ret_long, axis=0)
    rel_rank = vectorized_pct_rank(excess_long)

    bench = close[BENCHMARK]
    ma20 = bench.rolling(20).mean()
    ma60 = bench.rolling(60).mean()
    bear_mask = (ma20 < ma60).reindex(close.index).fillna(False)

    w_trend = pd.Series(0.60, index=close.index)
    w_rel = pd.Series(0.40, index=close.index)
    w_trend[bear_mask] = 0.40
    w_rel[bear_mask] = 0.60

    score = trend_z.mul(w_trend, axis=0) + rel_rank.mul(w_rel, axis=0)
    
    # MA50 filter: penalize ETFs below MA50
    ma50 = close[symbols].rolling(MA_FILTER_PERIOD).mean()
    below_ma50 = close[symbols] < ma50
    score[below_ma50] = score[below_ma50] - 1.0  # heavy penalty
    
    score[excess_long.isna()] = np.nan
    return score


def target_symbols_hysteresis(score_row, current_weights, holdings, stopped_out, cooldown, buffer=HYSTERESIS_BUFFER):
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


def target_weights_from_symbols(final_set, symbols, holdings):
    weights = pd.Series(0.0, index=symbols)
    if not final_set:
        return weights
    per_weight = min(1.0 / len(final_set), MAX_SYMBOL_WEIGHT)
    weights.loc[final_set] = per_weight
    return weights


def simulate(score_full, returns_full, close_full, symbols, dates, holdings, cost_rate_one_side=COST_RATE_ONE_SIDE):
    score = score_full.reindex(dates)
    returns = returns_full.reindex(dates)
    prices = close_full.reindex(dates)

    bench_close = close_full[BENCHMARK]
    bench_ma10 = bench_close.rolling(10).mean()
    bench_ma30 = bench_close.rolling(30).mean()
    bear_mask = (bench_ma10 < bench_ma30).reindex(dates).fillna(False)
    BEAR_SCALE = 0.50
    BULL_BOOST = 1.33

    current_weights = pd.Series(0.0, index=symbols)
    entry_price = {}
    cooldown_until = {}
    paused_until = None
    records = []
    stop_loss_events = 0

    for d in dates:
        day_price = prices.loc[d].reindex(symbols)
        day_returns = returns.loc[d].reindex(symbols).fillna(0.0)
        gross_return = float((current_weights * day_returns).sum())

        cooldown_active = {s for s, until in cooldown_until.items() if until >= d}

        stopped_out = set()
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

        if bear_mask.loc[d]:
            target = target * BEAR_SCALE
        else:
            target = target * BULL_BOOST

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
        records.append({
            "date": d, "gross_return": gross_return, "cost": cost,
            "net_return": net_return, "turnover": planned_turnover,
            "n_holdings": int((current_weights > 0).sum()),
        })

    result = pd.DataFrame(records).set_index("date")
    result.attrs["stop_loss_events"] = stop_loss_events
    return result


def annualized_return(daily_returns):
    if daily_returns.empty:
        return 0.0
    cumulative = float((1 + daily_returns).prod())
    n = len(daily_returns)
    if n == 0 or cumulative <= 0:
        return -1.0
    return cumulative ** (TRADING_DAYS_PER_YEAR / n) - 1


def max_drawdown_with_dates(daily_returns):
    if daily_returns.empty:
        return 0.0, "", ""
    equity = (1 + daily_returns).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1
    trough_date = dd.idxmin()
    peak_date = equity.loc[:trough_date].idxmax()
    return float(dd.min()), str(peak_date.date()), str(trough_date.date())


def max_drawdown(daily_returns):
    mdd, _, _ = max_drawdown_with_dates(daily_returns)
    return mdd


def sharpe_ratio(daily_returns):
    if daily_returns.empty or daily_returns.std(ddof=0) == 0:
        return 0.0
    return float(daily_returns.mean() / daily_returns.std(ddof=0) * np.sqrt(TRADING_DAYS_PER_YEAR))


def calmar_ratio(daily_returns):
    mdd = max_drawdown(daily_returns)
    if mdd == 0:
        return 0.0
    return annualized_return(daily_returns) / abs(mdd)


def grid_search_train(score_full, returns_full, close_full, symbols, train_dates):
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


def build_windows_expanding(all_dates):
    windows = []
    train_end_idx = MIN_TRAIN_DAYS
    while True:
        test_start_idx = train_end_idx + EMBARGO_DAYS
        test_end_idx = test_start_idx + TEST_TRADING_DAYS
        if test_end_idx > len(all_dates):
            break
        train_dates = all_dates[0:train_end_idx]
        test_dates = all_dates[test_start_idx:test_end_idx]
        assert train_dates[-1] < test_dates[0]
        windows.append((train_dates, test_dates))
        train_end_idx += STEP_TRADING_DAYS
    return windows


def benchmark_returns(close, dates):
    ret = close[BENCHMARK].pct_change().reindex(dates)
    return ret.fillna(0.0)


def run_walk_forward(close, symbols):
    t0 = time.time()
    score_full = compute_scores_full(close, symbols)
    returns_full = close[symbols].pct_change()
    print(f"[precompute] score computed in {time.time()-t0:.1f}s")

    all_dates = restrict_to_common_history(close, symbols)
    windows = build_windows_expanding(all_dates)
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

        window_records.append({
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
            "beat_bench": window_return > bench_window_return,
        })
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


def cost_erosion_test(score_full, returns_full, close_full, symbols, all_dates, windows_meta):
    results = {}
    for cost in [0.0, COST_RATE_ONE_SIDE]:
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
        ann_ret = annualized_return(full)
        results["zero_cost_annualized" if cost == 0.0 else "full_cost_annualized"] = round(ann_ret, 4)
    return results


def judge_report(close, symbols, result, version):
    windows = result["windows"]
    spliced = result["spliced_returns"]

    ann_ret = annualized_return(spliced)
    mdd, peak_date, trough_date = max_drawdown_with_dates(spliced)
    sharpe = sharpe_ratio(spliced)
    calmar = calmar_ratio(spliced)
    total_ret = float((1 + spliced).prod() - 1)

    n_windows = len(windows)
    beat_count = sum(1 for w in windows if w["beat_bench"])
    win_rate = beat_count / n_windows if n_windows else 0.0
    worst_window = min(w["window_return"] for w in windows) if windows else 0.0

    Ks = [w["best_K"] for w in windows]
    cv_K = float(np.std(Ks) / np.mean(Ks)) if Ks and np.mean(Ks) != 0 else 0.0

    consecutive = 0
    max_consecutive = 0
    for w in windows:
        if w["window_return"] < 0:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0

    all_dates = restrict_to_common_history(close, symbols)
    windows_for_cost = [
        {"test_start": pd.Timestamp(w["test_start"]), "test_end": pd.Timestamp(w["test_end"]), "best_K": w["best_K"]}
        for w in windows
    ]
    cost_result = cost_erosion_test(result["score_full"], result["returns_full"], close, symbols, all_dates, windows_for_cost)
    zero_cost = cost_result.get("zero_cost_annualized", 0.0)
    full_cost = cost_result.get("full_cost_annualized", 0.0)
    decay_rate = (zero_cost - full_cost) / zero_cost if zero_cost > 0 else 0.0

    up_windows = [w for w in windows if w["bench_window_return"] > 0]
    down_windows = [w for w in windows if w["bench_window_return"] <= 0]
    up_excess = float(np.mean([w["excess_vs_bench"] for w in up_windows])) if up_windows else 0.0
    down_excess = float(np.mean([w["excess_vs_bench"] for w in down_windows])) if down_windows else 0.0

    sorted_by_ret = sorted(windows, key=lambda w: w["window_return"], reverse=True)

    checklist = {
        "annualized_return_pass": ann_ret >= 0.12,
        "max_drawdown_pass": mdd >= -0.18,
        "sharpe_pass": sharpe >= 1.0,
        "win_rate_pass": win_rate >= 0.60,
        "worst_window_pass": worst_window >= -0.10,
        "param_cv_pass": cv_K <= 0.30,
        "cost_decay_pass": decay_rate <= 0.40,
        "max_consecutive_pass": max_consecutive <= 3,
    }

    report = {
        "version": version,
        "checklist": checklist,
        "all_pass": all(checklist.values()),
        "annualized_return": round(ann_ret, 4),
        "total_return": round(total_ret, 4),
        "max_drawdown": round(mdd, 4),
        "max_drawdown_period": f"{peak_date}~{trough_date}",
        "sharpe": round(sharpe, 4),
        "calmar": round(calmar, 4),
        "n_windows": n_windows,
        "beat_count": beat_count,
        "win_rate": round(win_rate, 4),
        "worst_window": round(worst_window, 4),
        "param_K_sequence": Ks,
        "param_cv_K": round(cv_K, 4),
        "max_consecutive_losing_windows": max_consecutive,
        "zero_cost_annualized": zero_cost,
        "full_cost_annualized": full_cost,
        "cost_decay_rate": round(decay_rate, 4),
        "up_market_avg_excess": round(up_excess, 4),
        "down_market_avg_excess": round(down_excess, 4),
        "top3_windows": [{"window": w["window"], "test_start": w["test_start"], "test_end": w["test_end"], "window_return": w["window_return"], "bench_window_return": w["bench_window_return"]} for w in sorted_by_ret[:3]],
        "bottom3_windows": [{"window": w["window"], "test_start": w["test_start"], "test_end": w["test_end"], "window_return": w["window_return"], "bench_window_return": w["bench_window_return"]} for w in sorted_by_ret[-3:]],
    }
    return report


def main():
    close, amount, symbols = load_data()
    symbols = liquidity_filter(amount, symbols)
    symbols = [s for s in symbols if s != "159611.SZ"]
    print(f"[universe] {len(symbols)} symbols: {symbols}")

    result = run_walk_forward(close, symbols)
    report = judge_report(close, symbols, result, "V52")

    print("\n=== JUDGE REPORT V52 ===")
    print(json.dumps({k: v for k, v in report.items()}, ensure_ascii=False, indent=2))

    output_dir = Path("/Users/ster/Desktop/fina/artifacts/backtest_v52")
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(result["windows"]).to_csv(output_dir / "windows.csv", index=False)
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved to {output_dir}")


if __name__ == "__main__":
    main()
