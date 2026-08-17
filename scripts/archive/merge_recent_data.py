"""增量合并: 保留research深度历史(2019~), 仅从clean补上新增交易日(7.17之后)."""
from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESEARCH_PATH = ROOT / "data" / "research" / "etf_daily_backtest.parquet"
CLEAN_PATH = ROOT / "data" / "clean" / "etf_daily.parquet"
MANIFEST_PATH = ROOT / "data" / "research" / "backtest_data_manifest.json"
MAX_DAILY_RETURN = 0.22


def main():
    research = pd.read_parquet(RESEARCH_PATH)
    research["date"] = pd.to_datetime(research["date"])
    clean = pd.read_parquet(CLEAN_PATH)
    clean["date"] = pd.to_datetime(clean["date"])

    research_symbols = set(research["symbol"].unique())
    before_rows = len(research)
    before_max_by_sym = research.groupby("symbol")["date"].max()

    # 只处理已存在于research中的symbol, 不引入历史不足的新symbol
    new_rows_list = []
    extended_symbols = []
    for sym in sorted(research_symbols):
        existing_max = before_max_by_sym.get(sym)
        clean_sub = clean[clean["symbol"] == sym]
        if clean_sub.empty or existing_max is None:
            continue
        fresh = clean_sub[clean_sub["date"] > existing_max]
        if fresh.empty:
            continue
        new_rows_list.append(fresh)
        extended_symbols.append((sym, existing_max.date(), fresh["date"].max().date(), len(fresh)))

    if not new_rows_list:
        print("[merge] 无新增交易日, research数据集已是最新")
        return

    new_rows = pd.concat(new_rows_list, ignore_index=True)

    # 数据质量校验: 拒绝新增行中的异常涨跌幅(与normalize_etf_daily一致的规则)
    extended_syms_set = {sym for sym, *_ in extended_symbols}
    rejected_syms = set()
    for sym in extended_syms_set:
        full_history = pd.concat(
            [research[research["symbol"] == sym], new_rows[new_rows["symbol"] == sym]],
            ignore_index=True,
        ).sort_values("date")
        ret = full_history["close"].pct_change()
        new_dates = set(new_rows.loc[new_rows["symbol"] == sym, "date"])
        bad = ret[(ret.abs() > MAX_DAILY_RETURN) & full_history["date"].isin(new_dates)]
        if not bad.empty:
            rejected_syms.add(sym)

    if rejected_syms:
        print(f"[merge] 拒绝 {len(rejected_syms)} 个标的的新增数据(异常涨跌幅): {sorted(rejected_syms)}")
        new_rows = new_rows[~new_rows["symbol"].isin(rejected_syms)]

    merged = pd.concat([research, new_rows], ignore_index=True)
    merged = merged.drop_duplicates(subset=["symbol", "date"], keep="last")
    merged = merged.sort_values(["symbol", "date"]).reset_index(drop=True)

    # 原子写入
    import os
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".parquet.tmp", dir=RESEARCH_PATH.parent)
    os.close(fd)
    try:
        merged.to_parquet(tmp, index=False)
        os.replace(tmp, RESEARCH_PATH)
    except BaseException:
        os.unlink(tmp)
        raise

    print(f"[merge] 合并完成: {before_rows} -> {len(merged)} 行 (+{len(merged) - before_rows})")
    print(f"[merge] 新日期范围: {merged['date'].min().date()} ~ {merged['date'].max().date()}")
    print(f"[merge] 扩展了 {len(extended_symbols)} 个标的的数据:")
    for sym, old_max, new_max, n in sorted(extended_symbols, key=lambda x: x[0]):
        print(f"    {sym}: {old_max} -> {new_max} (+{n}行)")

    unextended = research_symbols - {s for s, *_ in extended_symbols}
    if unextended:
        print(f"\n[merge] {len(unextended)} 个标的未获得新数据(本次采集未覆盖或已是最新): {sorted(unextended)}")

    manifest = {
        "merged_at": datetime.now(UTC).isoformat(),
        "before_rows": before_rows,
        "after_rows": len(merged),
        "date_range": [str(merged["date"].min().date()), str(merged["date"].max().date())],
        "extended_symbols": len(extended_symbols),
        "rejected_symbols": sorted(rejected_syms),
        "note": "增量合并: 从data/clean/etf_daily.parquet补充新增交易日, 保留原有深度历史",
    }
    MANIFEST_PATH.write_text(
        __import__("json").dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[merge] manifest已更新: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
