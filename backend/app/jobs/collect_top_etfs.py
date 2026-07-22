from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from app.collectors.akshare_collector import AkshareEtfCollector
from app.core.config import PROJECT_ROOT, settings
from app.normalizers.akshare import normalize_etf_daily, normalize_etf_spot
from app.storage.parquet_store import read_parquet, write_parquet


def _manifest_path() -> Path:
    return settings.clean_dir / "collection_manifest.json"


def _read_previous_manifest() -> dict[str, object]:
    path = _manifest_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(manifest: dict[str, object]) -> None:
    path = _manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_failure_manifest(
    *,
    provider: str,
    attempted_at: datetime,
    limit: int,
    lookback_days: int,
    failures: list[dict[str, str]],
    message: str,
) -> None:
    previous = _read_previous_manifest()
    manifest = {
        **previous,
        "provider": provider,
        "limit": limit,
        "lookback_days": lookback_days,
        "last_attempt_at": attempted_at.isoformat(),
        "last_attempt_status": "error",
        "last_error": message,
        "failures": failures,
    }
    _write_manifest(manifest)


def _replace_clean_outputs(tmp_basic: Path, tmp_daily: Path) -> None:
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    os.replace(tmp_basic, settings.clean_dir / "etf_basic.parquet")
    os.replace(tmp_daily, settings.clean_dir / "etf_daily.parquet")


def _cached_etf_basic(limit: int) -> pd.DataFrame:
    frame = read_parquet(settings.clean_dir / "etf_basic.parquet")
    if frame.empty:
        return frame
    return frame.sort_values("amount", ascending=False, na_position="last").head(limit).copy()


def _cached_raw_spot() -> pd.DataFrame:
    paths = sorted((settings.raw_dir / "akshare" / "etf_spot").glob("date=*/part.parquet"))
    if not paths:
        return pd.DataFrame()
    return read_parquet(paths[-1])


def _cached_daily_bars(symbol: str) -> pd.DataFrame:
    frame = read_parquet(settings.clean_dir / "etf_daily.parquet")
    if frame.empty or "symbol" not in frame.columns:
        return pd.DataFrame()
    return frame[frame["symbol"] == symbol].copy()


def _cached_raw_daily_bars(symbol: str, date_key: str) -> pd.DataFrame:
    return read_parquet(
        settings.raw_dir
        / "akshare"
        / "etf_daily"
        / f"symbol={symbol}"
        / f"date={date_key}"
        / "part.parquet"
    )


def _source_endpoints(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "source_endpoint" not in frame.columns:
        return []
    endpoints = {
        str(endpoint).strip()
        for endpoint in frame["source_endpoint"].dropna().unique()
        if str(endpoint).strip()
    }
    return sorted(endpoints)


def collect_top_etfs(limit: int = 200, lookback_days: int = 2520) -> dict[str, object]:
    collector = AkshareEtfCollector()
    collected_at = datetime.now(UTC)
    date_key = collected_at.strftime("%Y%m%d")
    failures: list[dict[str, str]] = []
    spot_rows = 0
    spot_source = "akshare_spot"
    spot_source_endpoints: list[str] = []

    try:
        raw_spot = collector.fetch_etf_universe()
        spot_rows = int(len(raw_spot))
        raw_spot_path = (
            settings.raw_dir / "akshare" / "etf_spot" / f"date={date_key}" / "part.parquet"
        )
        write_parquet(raw_spot, raw_spot_path)
        spot_source_endpoints = _source_endpoints(raw_spot)
        etf_basic = normalize_etf_spot(raw_spot, limit=limit)
    except Exception as exc:
        raw_spot = _cached_raw_spot()
        if not raw_spot.empty:
            spot_rows = int(len(raw_spot))
            spot_source = "cached_raw_etf_spot"
            spot_source_endpoints = _source_endpoints(raw_spot)
            etf_basic = normalize_etf_spot(raw_spot, limit=limit)
        else:
            etf_basic = _cached_etf_basic(limit=limit)
            spot_source = "cached_clean_etf_basic" if not etf_basic.empty else spot_source
        if etf_basic.empty:
            message = "ETF spot collection failed and no cached ETF universe is available."
            failures.append({"stage": "spot", "error": str(exc)})
            _write_failure_manifest(
                provider=collector.provider,
                attempted_at=collected_at,
                limit=limit,
                lookback_days=lookback_days,
                failures=failures,
                message=message,
            )
            raise RuntimeError(message) from exc
        failures.append(
            {
                "stage": "spot",
                "error": f"Spot collection failed; reused {spot_source}.",
            }
        )

    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    daily_frames: list[pd.DataFrame] = []
    daily_failures: list[dict[str, str]] = []
    daily_source_endpoints: set[str] = set()

    # 确保策略宇宙标的被纳入采集（即使不在成交额 top-N 中）
    strategy_universe_path = PROJECT_ROOT / "config" / "v58_universe.csv"
    all_symbols = set(etf_basic["symbol"].tolist())
    supplemented: list[str] = []
    if strategy_universe_path.exists():
        import csv as csv_mod
        with open(strategy_universe_path, encoding="utf-8") as f:
            for row in csv_mod.DictReader(f):
                sym = row["symbol"]
                if sym not in all_symbols:
                    all_symbols.add(sym)
                    supplemented.append(sym)
        if supplemented:
            print(f"[collect] supplemented {len(supplemented)} strategy-universe symbols: {supplemented}")

    for symbol in sorted(all_symbols):
        try:
            raw_daily = _cached_raw_daily_bars(symbol=symbol, date_key=date_key)
            if raw_daily.empty:
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
            daily_source_endpoints.update(_source_endpoints(raw_daily))
            daily_frames.append(normalize_etf_daily(raw_daily, symbol=symbol))
        except Exception as exc:  # noqa: BLE001
            cached_daily = _cached_daily_bars(symbol)
            if cached_daily.empty:
                daily_failures.append({"symbol": symbol, "error": str(exc)})
                continue
            failures.append(
                {
                    "symbol": symbol,
                    "error": "Daily collection failed; reused cached daily bars.",
                }
            )
            daily_source_endpoints.update(_source_endpoints(cached_daily))
            daily_frames.append(cached_daily)

    if daily_failures and not daily_frames:
        message = "ETF refresh did not complete; keeping previous clean data."
        failures.extend(daily_failures)
        _write_failure_manifest(
            provider=collector.provider,
            attempted_at=collected_at,
            limit=limit,
            lookback_days=lookback_days,
            failures=failures,
            message=message,
        )
        raise RuntimeError(message)
    failures.extend(daily_failures)

    etf_daily = pd.concat(daily_frames, ignore_index=True)
    tmp_dir = settings.clean_dir / "_tmp_refresh"
    tmp_basic = tmp_dir / "etf_basic.parquet"
    tmp_daily = tmp_dir / "etf_daily.parquet"
    write_parquet(etf_basic, tmp_basic)
    write_parquet(etf_daily, tmp_daily)
    _replace_clean_outputs(tmp_basic, tmp_daily)

    manifest = {
        "provider": collector.provider,
        "collected_at": collected_at.isoformat(),
        "last_attempt_at": collected_at.isoformat(),
        "last_attempt_status": "degraded" if failures else "ok",
        "last_error": None,
        "limit": limit,
        "lookback_days": lookback_days,
        "spot_rows": spot_rows,
        "spot_source": spot_source,
        "spot_source_endpoints": spot_source_endpoints,
        "selected_rows": int(len(etf_basic)),
        "daily_rows": int(len(etf_daily)),
        "daily_source_endpoints": sorted(daily_source_endpoints),
        "daily_missing_symbols": [item["symbol"] for item in daily_failures],
        "source_mixing_warning": (
            f"MIXED SOURCES: {sorted(daily_source_endpoints)}. "
            "Do not use for backtesting without reconciliation."
        ) if len(daily_source_endpoints) > 1 else None,
        "failures": failures,
    }
    _write_manifest(manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect top liquidity China-listed ETFs.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--lookback-days", type=int, default=2520)
    args = parser.parse_args()
    manifest = collect_top_etfs(limit=args.limit, lookback_days=args.lookback_days)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
