from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from .config import DEFAULT_CONFIG, StrategyConfig
from .data import restrict_to_common_history
from .engine import simulate
from .metrics import (
    annualized_return,
    calmar_ratio,
    max_drawdown_with_dates,
    sharpe_ratio,
)


def cost_erosion_test(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    close_full: pd.DataFrame,
    symbols: list[str],
    all_dates: pd.DatetimeIndex,
    windows_meta: list[dict],
    config: StrategyConfig = DEFAULT_CONFIG,
) -> dict[str, float]:
    results = {}
    for cost in [0.0, config.cost_rate_one_side]:
        cfg = replace(config, cost_rate_one_side=cost)
        spliced = []
        for w in windows_meta:
            test_dates = all_dates[
                (all_dates >= w["test_start"]) & (all_dates <= w["test_end"])
            ]
            sim = simulate(
                score_full, returns_full, close_full, symbols,
                test_dates, w["best_K"], cfg,
            )
            if sim.empty:
                continue
            step_dates = test_dates[: config.step_trading_days]
            spliced.append(sim["net_return"].reindex(step_dates).fillna(0.0))
        if not spliced:
            continue
        full = pd.concat(spliced).sort_index()
        full = full[~full.index.duplicated(keep="first")]
        ann_ret = annualized_return(full)
        label = "zero_cost_annualized" if cost == 0.0 else "full_cost_annualized"
        results[label] = round(ann_ret, 4)
    return results


def judge_report(
    close: pd.DataFrame,
    symbols: list[str],
    result: dict,
    version: str,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> dict:
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

    all_dates = restrict_to_common_history(close, symbols, config)
    windows_for_cost = [
        {
            "test_start": pd.Timestamp(w["test_start"]),
            "test_end": pd.Timestamp(w["test_end"]),
            "best_K": w["best_K"],
        }
        for w in windows
    ]
    cost_result = cost_erosion_test(
        result["score_full"], result["returns_full"],
        close, symbols, all_dates, windows_for_cost, config,
    )
    zero_cost = cost_result.get("zero_cost_annualized", 0.0)
    full_cost = cost_result.get("full_cost_annualized", 0.0)
    decay_rate = (zero_cost - full_cost) / zero_cost if zero_cost > 0 else 0.0

    up_windows = [w for w in windows if w["bench_window_return"] > 0]
    down_windows = [w for w in windows if w["bench_window_return"] <= 0]
    up_excess = (
        float(np.mean([w["excess_vs_bench"] for w in up_windows]))
        if up_windows
        else 0.0
    )
    down_excess = (
        float(np.mean([w["excess_vs_bench"] for w in down_windows]))
        if down_windows
        else 0.0
    )

    sorted_by_ret = sorted(windows, key=lambda w: w["window_return"], reverse=True)
    top3 = sorted_by_ret[:3]
    bottom3 = sorted_by_ret[-3:]

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
    all_pass = all(checklist.values())

    report = {
        "version": version,
        "checklist": checklist,
        "all_pass": all_pass,
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
        "total_reentry_events": result.get("total_reentry_events", 0),
        "top3_windows": [
            {
                "window": w["window"],
                "test_start": w["test_start"],
                "test_end": w["test_end"],
                "window_return": w["window_return"],
                "bench_window_return": w["bench_window_return"],
            }
            for w in top3
        ],
        "bottom3_windows": [
            {
                "window": w["window"],
                "test_start": w["test_start"],
                "test_end": w["test_end"],
                "window_return": w["window_return"],
                "bench_window_return": w["bench_window_return"],
            }
            for w in bottom3
        ],
        "windows_detail": windows,
    }
    return report
