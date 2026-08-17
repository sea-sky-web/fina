"""把clean层里全新的(research从未包含过的)标的追加进research深度数据集."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, UTC
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESEARCH_PATH = ROOT / "data" / "research" / "etf_daily_backtest.parquet"
CLEAN_PATH = ROOT / "data" / "clean" / "etf_daily.parquet"
MANIFEST_PATH = ROOT / "data" / "research" / "backtest_data_manifest.json"
MIN_ROWS_REQUIRED = 30  # 新标的至少要有这么多行才值得纳入


def main():
    research = pd.read_parquet(RESEARCH_PATH)
    research["date"] = pd.to_datetime(research["date"])
    clean = pd.read_parquet(CLEAN_PATH)
    clean["date"] = pd.to_datetime(clean["date"])

    existing_symbols = set(research["symbol"].unique())
    clean_symbols = set(clean["symbol"].unique())
    brand_new = sorted(clean_symbols - existing_symbols)

    if not brand_new:
        print("[add_new] 没有全新标的需要添加")
        return

    added_rows = []
    added_summary = []
    skipped = []

    for sym in brand_new:
        sub = clean[clean["symbol"] == sym].sort_values("date").copy()
        if len(sub) < MIN_ROWS_REQUIRED:
            skipped.append((sym, f"仅{len(sub)}行,低于最小要求{MIN_ROWS_REQUIRED}"))
            continue

        # 基础质量校验(与normalize_etf_daily一致的异常涨跌幅规则,双重保险)
        ret = sub["close"].pct_change()
        bad = ret[ret.abs() > 0.22]
        if not bad.empty:
            skipped.append((sym, f"存在{len(bad)}个异常涨跌幅(>22%)"))
            continue

        if sub["close"].isna().any() or (sub["close"] <= 0).any():
            skipped.append((sym, "存在NaN或非正收盘价"))
            continue

        added_rows.append(sub)
        added_summary.append((sym, sub["date"].min().date(), sub["date"].max().date(), len(sub)))

    if not added_rows:
        print(f"[add_new] {len(brand_new)}个候选标的全部未通过质量校验,无新增")
        for sym, reason in skipped:
            print(f"    跳过 {sym}: {reason}")
        return

    new_data = pd.concat(added_rows, ignore_index=True)
    merged = pd.concat([research, new_data], ignore_index=True)
    merged = merged.drop_duplicates(subset=["symbol", "date"], keep="last")
    merged = merged.sort_values(["symbol", "date"]).reset_index(drop=True)

    fd, tmp = tempfile.mkstemp(suffix=".parquet.tmp", dir=RESEARCH_PATH.parent)
    os.close(fd)
    try:
        merged.to_parquet(tmp, index=False)
        os.replace(tmp, RESEARCH_PATH)
    except BaseException:
        os.unlink(tmp)
        raise

    print(f"[add_new] 新增 {len(added_summary)} 个标的, {len(new_data)} 行")
    print(f"[add_new] research数据集: {len(research)} -> {len(merged)} 行, "
          f"symbol数 {research['symbol'].nunique()} -> {merged['symbol'].nunique()}")
    print()
    print("新增标的明细(历史深度从深到浅排序):")
    for sym, min_d, max_d, n in sorted(added_summary, key=lambda x: -x[3]):
        print(f"    {sym}: {min_d} ~ {max_d}  ({n}行, ~{n/243:.1f}年)")

    if skipped:
        print(f"\n跳过 {len(skipped)} 个未通过质量校验的候选标的:")
        for sym, reason in skipped:
            print(f"    {sym}: {reason}")

    manifest = {}
    if MANIFEST_PATH.exists():
        import json
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["expanded_at"] = datetime.now(UTC).isoformat()
    manifest["symbols_added"] = len(added_summary)
    manifest["symbols_skipped"] = len(skipped)
    manifest["total_symbols_after"] = int(merged["symbol"].nunique())
    manifest["note"] = manifest.get("note", "") + " | 标的池扩大: 新增标的追加进research(不影响已有标的历史)"
    import json as json_mod
    MANIFEST_PATH.write_text(json_mod.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
