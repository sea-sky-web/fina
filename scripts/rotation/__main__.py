"""入口：python -m rotation 或 python scripts/rotation_backtest.py"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import ARTIFACTS_DIR, DEFAULT_CONFIG, StrategyConfig
from .data import liquidity_filter, load_data
from .report import judge_report
from .walkforward import run_walk_forward


def main(config: StrategyConfig | None = None) -> None:
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


if __name__ == "__main__":
    main()
