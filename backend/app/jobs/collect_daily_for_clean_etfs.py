from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from app.collectors.akshare_collector import AkshareEtfCollector
from app.core.config import settings
from app.normalizers.akshare import normalize_etf_daily
from app.storage.parquet_store import read_parquet, write_parquet


def collect_daily_for_clean_etfs(lookback_days: int = 365) -> dict[str, object]:
    etf_basic = read_parquet(settings.clean_dir / "etf_basic.parquet")
    if etf_basic.empty:
        raise RuntimeError("No clean ETF universe found. Run collect_top_etfs first.")

    collector = AkshareEtfCollector()
    collected_at = datetime.now(UTC)
    date_key = collected_at.strftime("%Y%m%d")
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    daily_frames: list[pd.DataFrame] = []
    failures: list[dict[str, str]] = []

    for symbol in etf_basic["symbol"].tolist():
        try:
            raw_daily = collector.fetch_daily_bars(
                symbol=symbol,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
            raw_daily_path = (
                settings.raw_dir
                / "akshare"
                / "etf_daily"
                / f"symbol={symbol}"
                / f"date={date_key}"
                / "part.parquet"
            )
            write_parquet(raw_daily, raw_daily_path)
            daily_frames.append(normalize_etf_daily(raw_daily, symbol=symbol))
        except Exception as exc:  # noqa: BLE001
            failures.append({"symbol": symbol, "error": str(exc)})

    etf_daily = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    tmp_dir = settings.clean_dir / "_tmp_daily_refresh"
    tmp_daily = tmp_dir / "etf_daily.parquet"
    write_parquet(etf_daily, tmp_daily)
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    os.replace(tmp_daily, settings.clean_dir / "etf_daily.parquet")

    manifest_path = settings.clean_dir / "collection_manifest.json"
    previous_manifest = {}
    if manifest_path.exists():
        previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest = {
        **previous_manifest,
        "provider": collector.provider,
        "daily_collected_at": collected_at.isoformat(),
        "lookback_days": lookback_days,
        "daily_rows": int(len(etf_daily)),
        "failures": failures,
        "daily_failures": failures,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect daily bars for ETFs in clean universe.")
    parser.add_argument("--lookback-days", type=int, default=365)
    args = parser.parse_args()
    manifest = collect_daily_for_clean_etfs(lookback_days=args.lookback_days)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
