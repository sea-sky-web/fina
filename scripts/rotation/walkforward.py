from __future__ import annotations

import time

import numpy as np
import pandas as pd

from .asset_class import AssetClass, CLASS_BENCHMARK
from .config import (
    ClassConfig,
    MacroConfig,
    MultiAssetConfig,
    StrategyConfig,
    DEFAULT_CONFIG,
    DEFAULT_MULTI_CONFIG,
)
from .data import restrict_to_common_history
from .engine import simulate
from .macro import macro_allocate, run_macro_allocation
from .metrics import sharpe_ratio, calmar_ratio, max_drawdown
from .signals import compute_scores, compute_class_scores


# ---------------------------------------------------------------------------
# Single-class walk-forward (original, fully preserved)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Multi-asset walk-forward
# ---------------------------------------------------------------------------

def _build_windows_multi(
    all_dates: pd.DatetimeIndex,
    config: MultiAssetConfig,
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
        windows.append((train_dates, test_dates))
        train_end_idx += config.step_trading_days
    return windows


def _grid_search_class(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    close_full: pd.DataFrame,
    symbols: list[str],
    train_dates: pd.DatetimeIndex,
    cc: ClassConfig,
) -> tuple[int, float]:
    best = (cc.param_grid_k[0], -np.inf)
    for K in cc.param_grid_k:
        sim = simulate(
            score_full, returns_full, close_full, symbols,
            train_dates, K, class_config=cc,
        )
        if sim.empty:
            continue
        r = sim["net_return"]
        objective = sharpe_ratio(r) + calmar_ratio(r)
        if objective > best[1]:
            best = (K, objective)
    return best


def run_walk_forward_multi(
    close: pd.DataFrame,
    amount: pd.DataFrame,
    class_members: dict[AssetClass, list[str]],
    multi_config: MultiAssetConfig = DEFAULT_MULTI_CONFIG,
) -> dict:
    """两层多资产 walk-forward 回测.

    Layer 1: 每个 walk-forward 步骤开始时，用 in-sample 末端数据
             计算宏观资产配置权重.
    Layer 2: 对每个有权重的大类，类内做 grid-search + OOS 模拟.
    合并: 按 Layer 1 权重加权各类 OOS 日收益.
    """
    t0 = time.time()

    # 所有类别的 symbol 汇总
    all_syms: list[str] = []
    for members in class_members.values():
        all_syms.extend(members)
    all_syms = sorted(set(all_syms))

    # 收集各类的基准代码
    benchmarks = set()
    for cls in multi_config.enabled_classes():
        cc = multi_config.class_configs[cls]
        benchmarks.add(cc.benchmark)
    all_cols_needed = list(set(all_syms) | benchmarks)

    # 共同历史日期 — 只用有数据的列
    avail_cols = [c for c in all_cols_needed if c in close.columns]
    if not avail_cols:
        print("[walk_forward_multi] no data available")
        return {"windows": [], "spliced_returns": pd.Series(dtype=float), "mode": "multi_asset"}
    valid = close[avail_cols].dropna(how="all")
    all_dates = valid.index

    # 预计算各类的评分（跳过基准不在数据中的类）
    class_scores: dict[AssetClass, pd.DataFrame] = {}
    class_returns: dict[AssetClass, pd.DataFrame] = {}
    skipped_classes: list[str] = []
    for cls, members in class_members.items():
        if not members:
            continue
        cc = multi_config.class_configs[cls]
        if cc.benchmark not in close.columns:
            skipped_classes.append(f"{cls.value}(benchmark {cc.benchmark} missing)")
            continue
        avail_members = [s for s in members if s in close.columns]
        if not avail_members:
            continue
        class_scores[cls] = compute_class_scores(close, avail_members, amount, cc)
        class_returns[cls] = close[avail_members].pct_change()
    if skipped_classes:
        print(f"[multi-precompute] skipped: {', '.join(skipped_classes)}")
    print(f"[multi-precompute] {len(class_scores)} classes scored in {time.time() - t0:.1f}s")

    # 基准价格（用于 Layer 1）
    bench_prices: dict[AssetClass, pd.Series] = {}
    for cls in multi_config.enabled_classes():
        cc = multi_config.class_configs[cls]
        if cc.benchmark in close.columns:
            bench_prices[cls] = close[cc.benchmark]

    windows = _build_windows_multi(all_dates, multi_config)
    print(f"[walk_forward_multi] {len(windows)} windows")

    window_records = []
    spliced_returns = []

    for i, (train_dates, test_dates) in enumerate(windows):
        t1 = time.time()

        # Layer 1: 宏观配置（用 train 末端数据，避免前视）
        macro_w = macro_allocate(bench_prices, multi_config.macro, train_dates[-1])

        # Layer 2: 各类独立 grid-search + OOS 模拟
        class_oos_ret: dict[AssetClass, pd.Series] = {}

        for cls in multi_config.enabled_classes():
            w = macro_w.get(cls, 0.0)
            if w < 1e-6:
                continue
            if cls not in class_scores:
                continue

            cc = multi_config.class_configs[cls]
            members = [
                s for s in class_members.get(cls, [])
                if s in close.columns and s in class_scores[cls].columns
            ]
            if not members:
                continue

            best_K, _ = _grid_search_class(
                class_scores[cls], class_returns[cls],
                close, members, train_dates, cc,
            )

            test_sim = simulate(
                class_scores[cls], class_returns[cls],
                close, members, test_dates, best_K, class_config=cc,
            )
            if not test_sim.empty:
                class_oos_ret[cls] = test_sim["net_return"]

        # 合并各类 OOS 收益
        if class_oos_ret:
            combined = pd.Series(0.0, index=test_dates)
            for cls, ret_s in class_oos_ret.items():
                w = macro_w.get(cls, 0.0)
                aligned = ret_s.reindex(test_dates).fillna(0.0)
                combined += aligned * w
        else:
            combined = pd.Series(0.0, index=test_dates)

        step_dates = test_dates[: multi_config.step_trading_days]
        spliced_returns.append(combined.reindex(step_dates).fillna(0.0))

        window_return = float((1 + combined).prod() - 1)
        # 组合基准用沪深300
        bench_ret = close["510300.SH"].pct_change().reindex(test_dates).fillna(0.0)
        bench_window_return = float((1 + bench_ret).prod() - 1)

        alloc_desc = " ".join(
            f"{c.value[:4]}:{macro_w.get(c, 0):.0%}"
            for c in multi_config.enabled_classes()
            if macro_w.get(c, 0) > 0.01
        )
        class_k = {
            cls.value: best_K
            for cls in class_oos_ret
        } if class_oos_ret else {}

        window_records.append(
            {
                "window": i + 1,
                "train_start": str(train_dates[0].date()),
                "train_end": str(train_dates[-1].date()),
                "test_start": str(test_dates[0].date()),
                "test_end": str(test_dates[-1].date()),
                "macro_weights": {c.value: round(v, 3) for c, v in macro_w.items() if v > 0},
                "class_K": class_k,
                "window_return": round(window_return, 4),
                "bench_window_return": round(bench_window_return, 4),
                "excess_vs_bench": round(window_return - bench_window_return, 4),
                "window_max_drawdown": round(max_drawdown(combined), 4),
                "window_sharpe": round(sharpe_ratio(combined), 4),
                "beat_bench": window_return > bench_window_return,
            }
        )
        print(
            f"  W{i + 1:02d} [{test_dates[0].date()}~{test_dates[-1].date()}] "
            f"alloc=[{alloc_desc}] "
            f"ret={window_return:+.2%} bench={bench_window_return:+.2%} "
            f"({time.time() - t1:.1f}s)"
        )

    spliced = pd.concat(spliced_returns).sort_index()
    spliced = spliced[~spliced.index.duplicated(keep="first")]

    return {
        "windows": window_records,
        "spliced_returns": spliced,
        "mode": "multi_asset",
    }
