"""入口：python -m rotation 或 python scripts/rotation_backtest.py"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .asset_class import AssetClass, classify_etf
from .config import (
    ARTIFACTS_DIR,
    DEFAULT_CONFIG,
    DEFAULT_MULTI_CONFIG,
    MultiAssetConfig,
    StrategyConfig,
)
from .data import liquidity_filter, load_data
from .report import judge_report
from .walkforward import run_walk_forward, run_walk_forward_multi


def main(config: StrategyConfig | None = None) -> None:
    """单类模式入口（向后兼容）."""
    config = config or DEFAULT_CONFIG

    close, amount, symbols = load_data(config)
    symbols = liquidity_filter(amount, symbols, config)

    day_counts = close[symbols].count()
    short = [s for s in symbols if day_counts.get(s, 0) < config.min_history_days]
    if short:
        print(
            f"[history_filter] dropped {len(short)} symbols "
            f"with < {config.min_history_days} trading days"
        )
        symbols = [s for s in symbols if s not in short]

    print(f"[universe] {len(symbols)} symbols after all filters")

    result = run_walk_forward(close, symbols, amount, config)
    report = judge_report(close, symbols, result, "V64", config)

    print("\n=== JUDGE REPORT V64 ===")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "windows_detail"},
            ensure_ascii=False,
            indent=2,
        )
    )

    output_dir = ARTIFACTS_DIR / "backtest_v64"
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(result["windows"]).to_csv(output_dir / "windows.csv", index=False)
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"\nSaved detail to {output_dir}")


def main_multi(multi_config: MultiAssetConfig | None = None) -> None:
    """多资产两层模式入口."""
    multi_config = multi_config or DEFAULT_MULTI_CONFIG

    close, amount, all_symbols = load_data()
    print(f"[data] loaded {len(all_symbols)} symbols total")

    # 读取 ETF 名称用于分类
    from .config import PROJECT_ROOT
    basic_path = PROJECT_ROOT / "data" / "clean" / "etf_basic.parquet"
    name_map: dict[str, str] = {}
    if basic_path.exists():
        basic = pd.read_parquet(basic_path)
        name_map = dict(zip(basic["symbol"], basic["name"]))

    # 分类
    class_members: dict[AssetClass, list[str]] = {
        c: [] for c in AssetClass if c != AssetClass.EXCLUDED
    }
    for sym in all_symbols:
        cls = classify_etf(sym, name_map.get(sym, ""))
        if cls != AssetClass.EXCLUDED:
            class_members[cls].append(sym)

    # 各类流动性 + 历史过滤
    for cls in list(class_members.keys()):
        cc = multi_config.class_configs.get(cls)
        if cc is None:
            class_members.pop(cls, None)
            continue
        members = class_members[cls]
        avg_amt = amount[members].mean() if members else pd.Series(dtype=float)
        kept = [s for s in members if avg_amt.get(s, 0) >= cc.min_avg_amount]
        day_counts = close[kept].count() if kept else pd.Series(dtype=int)
        kept = [s for s in kept if day_counts.get(s, 0) >= cc.min_history_days]
        class_members[cls] = kept

    for cls, members in class_members.items():
        print(f"  [{cls.value}] {len(members)} symbols: {members[:8]}")

    result = run_walk_forward_multi(close, amount, class_members, multi_config)

    from .metrics import (
        annualized_return, max_drawdown_with_dates, sharpe_ratio, calmar_ratio,
    )
    spliced = result["spliced_returns"]
    ann_ret = annualized_return(spliced)
    total_ret = float((1 + spliced).prod() - 1)
    mdd, peak_d, trough_d = max_drawdown_with_dates(spliced)
    sharpe = sharpe_ratio(spliced)
    calmar = calmar_ratio(spliced)
    n_win = len(result["windows"])
    beat = sum(1 for w in result["windows"] if w["beat_bench"])

    print(f"\n{'='*60}")
    print("MULTI-ASSET WALK-FORWARD REPORT")
    print(f"{'='*60}")
    print(f"  年化收益:  {ann_ret:+.2%}")
    print(f"  总收益:    {total_ret:+.2%}")
    print(f"  最大回撤:  {mdd:.2%}  ({peak_d}~{trough_d})")
    print(f"  Sharpe:    {sharpe:.4f}")
    print(f"  Calmar:    {calmar:.4f}")
    print(f"  胜率:      {beat}/{n_win} = {beat/n_win:.1%}")

    output_dir = ARTIFACTS_DIR / "backtest_multi"
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(result["windows"]).to_csv(output_dir / "windows.csv", index=False)

    report = {
        "mode": "multi_asset",
        "annualized_return": round(ann_ret, 4),
        "total_return": round(total_ret, 4),
        "max_drawdown": round(mdd, 4),
        "max_drawdown_period": f"{peak_d}~{trough_d}",
        "sharpe": round(sharpe, 4),
        "calmar": round(calmar, 4),
        "n_windows": n_win,
        "beat_count": beat,
        "win_rate": round(beat / n_win, 4) if n_win else 0,
        "windows": result["windows"],
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"\nSaved to {output_dir}")


if __name__ == "__main__":
    import sys
    if "--multi" in sys.argv:
        main_multi()
    else:
        main()
