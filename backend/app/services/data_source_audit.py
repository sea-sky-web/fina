from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from app.core.config import settings
from app.models import DataSourceAudit
from app.storage.parquet_store import read_parquet

APPROVED_MARKET_DATA_PROVIDERS = {"akshare"}
NON_PRODUCTION_PROVIDER_VALUES = {
    "demo",
    "fake",
    "fixture",
    "local",
    "mock",
    "sample",
    "synthetic",
    "test",
    "unknown",
}


def _manifest() -> dict[str, Any]:
    path = settings.clean_dir / "collection_manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _provider_values(*frames: pd.DataFrame) -> set[str]:
    values: set[str] = set()
    for frame in frames:
        if frame.empty or "provider" not in frame.columns:
            continue
        values.update(str(value).strip().lower() for value in frame["provider"].dropna().unique())
    return values


def _source_endpoints(*frames: pd.DataFrame) -> list[str]:
    endpoints: set[str] = set()
    for frame in frames:
        if frame.empty or "source_endpoint" not in frame.columns:
            continue
        endpoints.update(str(value).strip() for value in frame["source_endpoint"].dropna().unique())
    return sorted(endpoint for endpoint in endpoints if endpoint)


def _latest_trade_date(frame: pd.DataFrame) -> date | None:
    if frame.empty or "date" not in frame.columns or frame["date"].isna().all():
        return None
    return pd.to_datetime(frame["date"], errors="coerce").dt.date.max()


def _cached_sources(manifest: dict[str, Any]) -> list[str]:
    output = []
    spot_source = str(manifest.get("spot_source") or "")
    if spot_source.startswith("cached_"):
        output.append(spot_source)
    for failure in manifest.get("failures") or []:
        text = " ".join(str(value) for value in failure.values())
        if "cached" in text.lower():
            output.append(text)
    return output


def audit_data_sources() -> DataSourceAudit:
    manifest = _manifest()
    etf_basic = read_parquet(settings.clean_dir / "etf_basic.parquet")
    etf_daily = read_parquet(settings.clean_dir / "etf_daily.parquet")
    warnings: list[str] = []
    errors: list[str] = []

    if etf_basic.empty:
        errors.append("clean etf_basic is empty; no production ETF universe is available.")
    if etf_daily.empty:
        errors.append("clean etf_daily is empty; no production daily bars are available.")

    provider = str(manifest.get("provider") or "unknown").lower()
    provider_values = _provider_values(etf_basic, etf_daily)
    if provider not in APPROVED_MARKET_DATA_PROVIDERS:
        errors.append(f"manifest provider is not approved for production market data: {provider}.")
    bad_values = provider_values & NON_PRODUCTION_PROVIDER_VALUES
    if bad_values:
        errors.append(
            f"clean market data contains non-production provider values: {sorted(bad_values)}."
        )
    unexpected_values = provider_values - APPROVED_MARKET_DATA_PROVIDERS
    if unexpected_values:
        errors.append(
            f"clean market data contains unapproved provider values: {sorted(unexpected_values)}."
        )

    manifest_status = str(manifest.get("last_attempt_status") or "")
    if manifest_status == "error":
        errors.append(
            "last data collection attempt failed: "
            f"{manifest.get('last_error') or 'unknown error'}."
        )
    elif manifest_status == "degraded":
        warnings.append(
            "last data collection completed in degraded mode; inspect failures before use."
        )

    latest_trade_date = _latest_trade_date(etf_daily)
    if latest_trade_date is None:
        errors.append("latest trade date is unavailable from clean etf_daily.")
    else:
        age_days = (date.today() - latest_trade_date).days
        if age_days > settings.data_stale_after_days:
            errors.append(
                f"clean daily data is {age_days} calendar days behind local date; "
                "refresh is required."
            )

    source_endpoints = sorted(
        {
            *_source_endpoints(etf_basic, etf_daily),
            *(str(item) for item in manifest.get("spot_source_endpoints") or []),
            *(str(item) for item in manifest.get("daily_source_endpoints") or []),
        }
    )
    if not source_endpoints:
        warnings.append(
            "clean data does not expose source_endpoint yet; refresh with the current collector."
        )

    cached_sources = _cached_sources(manifest)
    if cached_sources:
        warnings.append(
            "some data came from cached fallback rather than a fresh provider response."
        )

    symbols_total = int(etf_basic["symbol"].nunique()) if "symbol" in etf_basic.columns else 0
    symbols_with_daily = int(etf_daily["symbol"].nunique()) if "symbol" in etf_daily.columns else 0
    if symbols_total and symbols_with_daily < symbols_total:
        warnings.append(
            f"daily bars cover {symbols_with_daily}/{symbols_total} selected ETFs."
        )

    daily_missing_symbols = [
        str(symbol)
        for symbol in (manifest.get("daily_missing_symbols") or [])
        if symbol
    ]
    if daily_missing_symbols:
        warnings.append(f"missing daily bars: {', '.join(daily_missing_symbols)}.")

    collected_at = _parse_datetime(manifest.get("collected_at"))
    status = "error" if errors else "warning" if warnings else "ok"
    return DataSourceAudit(
        generated_at=datetime.now(UTC),
        ok=not errors,
        status=status,
        provider=provider,
        manifest_status=manifest_status or None,
        collected_at=collected_at,
        spot_source=str(manifest.get("spot_source") or "") or None,
        selected_rows=int(manifest.get("selected_rows", 0) or 0),
        basic_rows=int(len(etf_basic)),
        daily_rows=int(len(etf_daily)),
        latest_trade_date=latest_trade_date,
        symbols_total=symbols_total,
        symbols_with_daily=symbols_with_daily,
        daily_missing_symbols=daily_missing_symbols,
        source_endpoints=source_endpoints,
        cached_sources=cached_sources,
        warnings=warnings,
        errors=errors,
    )
