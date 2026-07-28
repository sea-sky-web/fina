from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
import time
from typing import Any

import pandas as pd
import requests

from app.collectors.base import EtfDataCollector

DEFAULT_REQUEST_TIMEOUT_SECONDS = 12
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 5


def _create_session(timeout: int = DEFAULT_REQUEST_TIMEOUT_SECONDS) -> requests.Session:
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.request = _with_default_timeout(session.request, timeout)
    return session


def _with_default_timeout(func, timeout):
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        kwargs.setdefault("timeout", timeout)
        return func(*args, **kwargs)
    return wrapper


def _retry_on_disconnect(max_retries=MAX_RETRIES, base_backoff=BASE_BACKOFF_SECONDS):
    """Retry with exponential backoff on transient errors."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (ConnectionError, OSError, requests.Timeout, requests.ConnectionError) as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        wait = base_backoff * (2 ** attempt)
                        time.sleep(wait)
            raise last_exc

        return wrapper

    return decorator


class AkshareEtfCollector(EtfDataCollector):
    provider = "akshare"

    @_retry_on_disconnect(max_retries=3, base_backoff=5)
    def fetch_etf_universe(self) -> pd.DataFrame:
        import akshare as ak

        frame = ak.fund_etf_spot_em()
        if frame is None or frame.empty:
            raise ValueError("AKShare returned empty ETF universe")
        frame["source_endpoint"] = "fund_etf_spot_em"
        frame["provider"] = self.provider
        frame["updated_at"] = datetime.now(UTC)
        return frame

    @_retry_on_disconnect(max_retries=3, base_backoff=2)
    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        import akshare as ak

        code = symbol.split(".")[0]
        frame = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        if frame is None or frame.empty:
            raise ValueError(f"AKShare returned empty daily bars for {symbol}")
        frame["source_endpoint"] = "fund_etf_hist_em"
        frame["symbol"] = symbol
        frame["provider"] = self.provider
        frame["updated_at"] = datetime.now(UTC)
        return frame
