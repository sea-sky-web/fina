"""三层交叉验证编排器."""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from .bt_backtest import bt_simulate
from .config import ARTIFACTS_DIR, DEFAULT_CONFIG, StrategyConfig
from .data import liquidity_filter, load_data
from .metrics import annualized_return, max_drawdown, sharpe_ratio
from .vec_backtest import vec_simulate
from .walkforward import run_walk_forward


def _extract_k_schedule(wfo_result: dict, config: StrategyConfig) -> list[dict]:
    return [
        {
            "test_start": w["test_start"],
            "test_end": w["test_end"],
            "best_K": w["best_K"],
            "step_days": config.step_trading_days,
        }
        for w in wfo_result["windows"]
    ]


def _compare(a: pd.Series, b: pd.Series, label: str) -> dict:
    common = a.index.intersection(b.index)
    if common.empty:
        return {"label": label, "n_common": 0, "verdict": "NO_DATA"}

    x = a.reindex(common).fillna(0.0)
    y = b.reindex(common).fillna(0.0)
    diff = x - y

    corr = float(np.corrcoef(x.values, y.values)[0, 1]) if len(common) > 1 else 0.0
    cum_x = float((1 + x).prod())
    cum_y = float((1 + y).prod())
    cum_drift = abs(cum_x - cum_y) / max(abs(cum_x), 1e-9)

    return {
        "label": label,
        "n_common": len(common),
        "correlation": round(corr, 6),
        "max_abs_daily_diff": round(float(diff.abs().max()), 6),
        "mean_abs_daily_diff": round(float(diff.abs().mean()), 6),
        "rmse": round(float(np.sqrt((diff ** 2).mean())), 6),
        "cumulative_a": round(cum_x, 6),
        "cumulative_b": round(cum_y, 6),
        "cumulative_drift_pct": round(cum_drift * 100, 4),
    }


def _verdict(comparisons: dict) -> str:
    wfo_bt = comparisons["wfo_vs_bt"]

    if wfo_bt.get("n_common", 0) == 0:
        return "NO_DATA"

    bt_corr = wfo_bt.get("correlation", 0)
    bt_drift = wfo_bt.get("cumulative_drift_pct", 100)

    # 主要看累计漂移（总收益是否匹配）
    # 日相关系数作为辅助（窗口边界状态差异会降低日相关系数但不影响总收益）
    if bt_drift < 1.0 and bt_corr >= 0.95:
        return "PASS"
    if bt_drift < 3.0 and bt_corr >= 0.90:
        return "WARN"
    return "FAIL"


def run_triple_validation(
    config: StrategyConfig = DEFAULT_CONFIG,
) -> dict:
    print("=" * 60)
    print("三层交叉验证 (Triple-Layer Cross Validation)")
    print("=" * 60)

    # 数据加载
    close, amount, symbols = load_data(config)
    symbols = liquidity_filter(amount, symbols, config)
    day_counts = close[symbols].count()
    symbols = [s for s in symbols if day_counts.get(s, 0) >= config.min_history_days]
    print(f"[data] {len(symbols)} symbols after filters")

    # Layer 1: WFO
    print("\n--- Layer 1: WFO (Walk-Forward Optimization) ---")
    t0 = time.time()
    wfo = run_walk_forward(close, symbols, amount, config)
    wfo_time = time.time() - t0
    wfo_ret = wfo["spliced_returns"]
    print(f"  WFO done in {wfo_time:.1f}s, {len(wfo_ret)} days")
    print(f"  WFO cumulative: {float((1 + wfo_ret).prod()):.6f}")

    k_schedule = _extract_k_schedule(wfo, config)

    # Layer 2: VEC
    print("\n--- Layer 2: VEC (Vectorized Backtest) ---")
    t1 = time.time()
    vec_ret = vec_simulate(wfo["score_full"], close, symbols, k_schedule, config)
    vec_time = time.time() - t1
    print(f"  VEC done in {vec_time:.1f}s, {len(vec_ret)} days")
    print(f"  VEC cumulative: {float((1 + vec_ret).prod()):.6f}")

    # Layer 3: BT
    print("\n--- Layer 3: BT (Event-Driven Backtest) ---")
    t2 = time.time()
    bt_ret = bt_simulate(wfo["score_full"], close, symbols, k_schedule, config)
    bt_time = time.time() - t2
    print(f"  BT done in {bt_time:.1f}s, {len(bt_ret)} days")
    print(f"  BT cumulative: {float((1 + bt_ret).prod()):.6f}")
    print(f"  BT stop-loss events: {bt_ret.attrs.get('stop_loss_events', 'N/A')}")
    print(f"  BT re-entry events: {bt_ret.attrs.get('reentry_events', 'N/A')}")

    # 比对
    print("\n--- Cross Comparison ---")
    comparisons = {
        "wfo_vs_vec": _compare(wfo_ret, vec_ret, "WFO vs VEC"),
        "wfo_vs_bt": _compare(wfo_ret, bt_ret, "WFO vs BT"),
        "vec_vs_bt": _compare(vec_ret, bt_ret, "VEC vs BT"),
    }

    for comp in comparisons.values():
        print(f"\n  [{comp['label']}]")
        print(f"    Days compared: {comp['n_common']}")
        print(f"    Correlation:   {comp.get('correlation', 'N/A')}")
        print(f"    Max daily diff:{comp.get('max_abs_daily_diff', 'N/A')}")
        print(f"    RMSE:          {comp.get('rmse', 'N/A')}")
        print(f"    Cumulative A:  {comp.get('cumulative_a', 'N/A')}")
        print(f"    Cumulative B:  {comp.get('cumulative_b', 'N/A')}")
        print(f"    Cum. drift:    {comp.get('cumulative_drift_pct', 'N/A')}%")

    v = _verdict(comparisons)
    print(f"\n{'=' * 60}")
    print(f"  VERDICT: {v}")
    print(f"{'=' * 60}")

    # 各层指标对比
    layers = {"WFO": wfo_ret, "VEC": vec_ret, "BT": bt_ret}
    metrics_table = {}
    for name, ret in layers.items():
        if ret.empty:
            continue
        metrics_table[name] = {
            "annualized_return": round(annualized_return(ret), 4),
            "max_drawdown": round(max_drawdown(ret), 4),
            "sharpe": round(sharpe_ratio(ret), 4),
            "total_return": round(float((1 + ret).prod() - 1), 4),
        }

    print("\n  Metrics comparison:")
    print(f"  {'':8s} {'Ann.Ret':>10s} {'MaxDD':>10s} {'Sharpe':>10s} {'TotalRet':>10s}")
    for name, m in metrics_table.items():
        print(
            f"  {name:8s} {m['annualized_return']:>+10.2%} "
            f"{m['max_drawdown']:>10.2%} "
            f"{m['sharpe']:>10.4f} "
            f"{m['total_return']:>+10.2%}"
        )

    # 保存
    output_dir = ARTIFACTS_DIR / "validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "verdict": v,
        "comparisons": comparisons,
        "metrics": metrics_table,
        "timing": {
            "wfo_seconds": round(wfo_time, 1),
            "vec_seconds": round(vec_time, 1),
            "bt_seconds": round(bt_time, 1),
        },
        "wfo_stop_loss_events": wfo.get("total_stop_loss_events", 0),
        "wfo_reentry_events": wfo.get("total_reentry_events", 0),
        "bt_stop_loss_events": bt_ret.attrs.get("stop_loss_events", 0),
        "bt_reentry_events": bt_ret.attrs.get("reentry_events", 0),
    }
    (output_dir / "triple_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"\n  Saved to {output_dir / 'triple_validation.json'}")

    return report
