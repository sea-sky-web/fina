from datetime import date

import pandas as pd

from app.core.config import settings
from app.models import EtfBasic, EtfDailyBar
from app.services.records import dataframe_records
from app.services.theme_classifier import infer_etf_theme
from app.storage.parquet_store import read_parquet


def _with_theme(record: dict) -> dict:
    if not record.get("theme"):
        record["theme"] = infer_etf_theme(
            name=record.get("name"),
            index_name=record.get("index_name"),
        )
    return record


def list_etfs(limit: int = 100) -> list[EtfBasic]:
    clean_path = settings.clean_dir / "etf_basic.parquet"
    frame = read_parquet(clean_path)
    if not frame.empty:
        frame = frame.sort_values("amount", ascending=False, na_position="last").head(limit)
        return [EtfBasic(**_with_theme(record)) for record in dataframe_records(frame)]

    return []


def get_etf_daily(
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    limit: int = 250,
) -> list[EtfDailyBar]:
    clean_path = settings.clean_dir / "etf_daily.parquet"
    frame = read_parquet(clean_path)
    if not frame.empty:
        frame = frame[frame["symbol"] == symbol].copy()
        if start is not None:
            frame = frame[pd.to_datetime(frame["date"]).dt.date >= start]
        if end is not None:
            frame = frame[pd.to_datetime(frame["date"]).dt.date <= end]
        frame = frame.sort_values("date").tail(limit)
        return [EtfDailyBar(**record) for record in dataframe_records(frame)]

    return []
