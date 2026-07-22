from __future__ import annotations

import time

import numpy as np
import pandas as pd

from .config import StrategyConfig, DEFAULT_CONFIG
from .data import restrict_to_common_history
from .engine import simulate
from .metrics import sharpe_ratio, calmar_ratio, max_drawdown
from .signals import compute_scores


def build_windows_expanding(
    all_dates: pd.DatetimeIndex,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> list[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    windows = []
    train_end_idx = config.min_train_days
    while True:
        test_start_idx = train_end_idx + config.embargo_days
        test_end_idx = test_start_idx + config.test_trading_days
        if test_end_idx > len(all_dates):
            break
        train_dates = all_dates[0:train_end_idx]
        test_dates = all_dates[test_start_idx:test_end_idx]
        assert train_dates[-1] < test_dates[0], "lookahead detected: train overlaps test"
        gap_days = (test_dates[0] - train_dates[-1]).days
        assert gap_days >= 1, "embargo gap violated"
        windows.append((train_dates, test_dates))
        train_end_idx += config.step_trading_days
    return windows


def grid_search_train(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    close_full: pd.DataFrame,
    symbols: list[str],
    train_dates: pd.DatetimeIndex,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> tuple[int, float]:
    best = (config.param_grid_k[0], -np.inf)
    for K in config.param_grid_k:
        sim = simulate(
            score_full, returns_full, close_full, symbols, train_dates, K, config,
        )
        if sim.empty:
            continue
        r = sim["net_return"]
        objective = sharpe_ratio(r) + calmar_ratio(r)
        if objective > best[1]:
            best = (K, objective)
    return best


def benchmark_returns(
    close: pd.DataFrame,
    dates: pd.DatetimeIndex,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> pd.Series:
    ret = close[config.benchmark].pct_change().reindex(dates)
    return ret.fillna(0.0)


def run_walk_forward(
    close: pd.DataFrame,
    symbols: list[str],
    amount: pd.DataFrame,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> dict:
    t0 = time.time()
    score_full = compute_scores(close, symbols, amount, config)
    returns_full = close[symbols].pct_change()
    print(f"[precompute] score computed in {time.time() - t0:.1f}s")

    all_dates = restrict_to_common_history(close, symbols, config)
    windows = build_windows_expanding(all_dates, config)
    print(
        f"[walk_forward] total windows: {len(windows)} "
        f"(expanding train, embargo={config.embargo_days}d)"
    )

    window_records = []
    spliced_returns = []
    all_turnovers = []
    total_stop_loss_events = 0
    total_reentry_events = 0

    for i, (train_dates, test_dates) in enumerate(windows):
        t1 = time.time()
        best_K, train_obj = grid_search_train(
            score_full, returns_full, close, symbols, train_dates, config,
        )
        test_sim = simulate(
            score_full, returns_full, close, symbols, test_dates, best_K, config,
        )
        test_ret = (
            test_sim["net_return"] if not test_sim.empty else pd.Series(dtype=float)
        )
        if not test_sim.empty:
            all_turnovers.append(test_sim["turnover"])
            total_stop_loss_events += test_sim.attrs.get("stop_loss_events", 0)
            total_reentry_events += test_sim.attrs.get("reentry_events", 0)

        bench_ret = benchmark_returns(close, test_dates, config)

        window_return = (
            float((1 + test_ret).prod() - 1) if not test_ret.empty else 0.0
        )
        bench_window_return = float((1 + bench_ret).prod() - 1)
        window_mdd = max_drawdown(test_ret)
        window_sharpe = sharpe_ratio(test_ret)

        step_dates = test_dates[: config.step_trading_days]
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
                "beat_bench": window_return > bench_window_return,
            }
        )
        print(
            f"  W{i + 1:02d} [{test_dates[0].date()}~{test_dates[-1].date()}] "
            f"train_days={len(train_dates)} K={best_K} "
            f"ret={window_return:+.2%} bench={bench_window_return:+.2%} "
            f"excess={window_return - bench_window_return:+.2%} "
            f"mdd={window_mdd:.2%} ({time.time() - t1:.1f}s)"
        )

    spliced = pd.concat(spliced_returns).sort_index()
    spliced = spliced[~spliced.index.duplicated(keep="first")]
    avg_turnover = (
        float(pd.concat(all_turnovers).mean()) if all_turnovers else 0.0
    )

    return {
        "windows": window_records,
        "spliced_returns": spliced,
        "score_full": score_full,
        "returns_full": returns_full,
        "avg_daily_turnover": avg_turnover,
        "total_stop_loss_events": total_stop_loss_events,
        "total_reentry_events": total_reentry_events,
    }
