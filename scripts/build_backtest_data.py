"""
构建回测用 ETF 日线数据（从 clean parquet 过滤校验输出）

用法:
    PYTHONPATH=backend python scripts/build_backtest_data.py [--source PATH] [--universe PATH]

输入:  data/clean/etf_daily.parquet（collect_top_etfs 的输出）
输出:  data/research/etf_daily_backtest.parquet + backtest_data_manifest.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, UTC
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT / "data" / "clean" / "etf_daily.parquet"
OUTPUT_DIR = PROJECT_ROOT / "data" / "research"
OUTPUT_PARQUET = OUTPUT_DIR / "etf_daily_backtest.parquet"
OUTPUT_MANIFEST = OUTPUT_DIR / "backtest_data_manifest.json"
MAX_DAILY_RETURN = 0.22


def build(source_path: Path, universe_path: Path | None = None) -> None:
    print(f"[build] reading {source_path}")
    df = pd.read_parquet(source_path)
    df["date"] = pd.to_datetime(df["date"])
    initial_symbols = sorted(df["symbol"].unique())
    initial_rows = len(df)
    print(f"[build] loaded {initial_rows} rows, {len(initial_symbols)} symbols")

    rejected: dict[str, str] = {}

    if "source_endpoint" in df.columns:
        sina_symbols = df[df["source_endpoint"] == "fund_etf_hist_sina"]["symbol"].unique()
        for s in sina_symbols:
            rejected[s] = "uses fund_etf_hist_sina"
        df = df[~df["symbol"].isin(sina_symbols)].copy()
        if sina_symbols.size:
            print(f"[build] dropped {len(sina_symbols)} Sina-source symbols")

    if universe_path and universe_path.exists():
        universe_df = pd.read_csv(universe_path)
        if "symbol" in universe_df.columns:
            keep = set(universe_df["symbol"].tolist())
            df = df[df["symbol"].isin(keep)].copy()
            print(f"[build] filtered to {len(keep)} universe symbols")

    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    bad_symbols = set()
    for sym, grp in df.groupby("symbol"):
        ret = grp["close"].pct_change().dropna()
        if (ret.abs() > MAX_DAILY_RETURN).any():
            bad_symbols.add(sym)
            bad_dates = grp.loc[ret[ret.abs() > MAX_DAILY_RETURN].index, "date"].dt.date.tolist()
            rejected[sym] = f"returns exceed +/-{MAX_DAILY_RETURN:.0%} on {bad_dates[:3]}"

    if bad_symbols:
        df = df[~df["symbol"].isin(bad_symbols)].copy()
        print(f"[build] dropped {len(bad_symbols)} symbols with abnormal returns: {sorted(bad_symbols)}")

    final_symbols = sorted(df["symbol"].unique())
    print(f"[build] final: {len(df)} rows, {len(final_symbols)} symbols")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_PARQUET, index=False)

    date_range = [str(df["date"].min().date()), str(df["date"].max().date())] if len(df) else []
    sources = sorted(df["source_endpoint"].unique().tolist()) if "source_endpoint" in df.columns else []

    manifest = {
        "built_at": datetime.now(UTC).isoformat(),
        "source_file": str(source_path),
        "rows": len(df),
        "symbols": final_symbols,
        "symbol_count": len(final_symbols),
        "date_range": date_range,
        "source_endpoints": sources,
        "rejected_symbols": rejected,
        "max_daily_return_threshold": MAX_DAILY_RETURN,
    }
    OUTPUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[build] wrote {OUTPUT_PARQUET}")
    print(f"[build] wrote {OUTPUT_MANIFEST}")
    if rejected:
        print(f"[build] rejected symbols:")
        for sym, reason in sorted(rejected.items()):
            print(f"  {sym}: {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build backtest ETF daily data")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--universe", type=Path, default=None)
    args = parser.parse_args()
    build(args.source, args.universe)


if __name__ == "__main__":
    main()
