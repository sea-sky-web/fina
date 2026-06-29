import json
from datetime import date, datetime

import pandas as pd

from app.core.config import settings
from app.models import DataStatus
from app.storage.parquet_store import read_parquet


def _manifest() -> dict:
    path = settings.clean_dir / "collection_manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _status_from_frame(dataset: str, frame: pd.DataFrame, manifest: dict) -> DataStatus:
    if frame.empty:
        last_error = manifest.get("last_error")
        message = "No clean data has been collected yet."
        if last_error:
            message = f"No clean data is available. Last refresh failed: {last_error}"
        return DataStatus(
            provider=manifest.get("provider", "akshare"),
            dataset=dataset,
            last_success_at=None,
            rows=0,
            status="empty" if not last_error else "error",
            message=message,
        )

    last_trade_date = None
    if "date" in frame.columns and not frame["date"].isna().all():
        last_trade_date = pd.to_datetime(frame["date"]).dt.date.max()

    failures = manifest.get("failures") or []
    last_attempt_status = manifest.get("last_attempt_status")
    status = "ok" if not failures and last_attempt_status not in {"error", "degraded"} else "stale"
    message = "Clean data is available."
    if failures:
        issue_count = len(failures)
        message = f"Clean data is available; last refresh used fallback for {issue_count} issue(s)."
    if last_attempt_status == "error" and manifest.get("last_error"):
        message = f"Showing previous clean data. Last refresh failed: {manifest['last_error']}"
    if last_attempt_status == "degraded":
        message = (
            "Clean data is available; last refresh completed with provider fallback "
            "or partial daily data."
        )
    if last_trade_date is not None:
        data_age_days = (date.today() - last_trade_date).days
        if data_age_days > settings.data_stale_after_days:
            status = "stale"
            message = (
                f"Clean data is {data_age_days} calendar days behind "
                f"latest local date; refresh is required."
            )

    collected_at = manifest.get("collected_at")
    return DataStatus(
        provider=manifest.get("provider", "akshare"),
        dataset=dataset,
        last_success_at=datetime.fromisoformat(collected_at) if collected_at else None,
        last_trade_date=last_trade_date,
        rows=int(len(frame)),
        status=status,
        message=message,
    )


def get_data_status() -> list[DataStatus]:
    manifest = _manifest()
    etf_basic = read_parquet(settings.clean_dir / "etf_basic.parquet")
    etf_daily = read_parquet(settings.clean_dir / "etf_daily.parquet")
    factors_processed = read_parquet(settings.clean_dir / "factors_processed.parquet")
    return [
        _status_from_frame("etf_basic", etf_basic, manifest),
        _status_from_frame("etf_daily", etf_daily, manifest),
        _status_from_frame("factors_processed", factors_processed, manifest),
    ]
