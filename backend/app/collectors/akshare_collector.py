from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
import time
from typing import Any

import pandas as pd

from app.collectors.base import EtfDataCollector

DEFAULT_REQUEST_TIMEOUT_SECONDS = 12
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 5


@contextmanager
def _requests_default_timeout(seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS) -> Iterator[None]:
    """Apply a default timeout to AKShare internals that call requests without one."""
    import requests

    original_get = requests.get
    original_post = requests.post

    def _with_default_timeout(func):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            kwargs.setdefault("timeout", seconds)
            return func(*args, **kwargs)

        return wrapper

    requests.get = _with_default_timeout(original_get)
    requests.post = _with_default_timeout(original_post)
    try:
        yield
    finally:
        requests.get = original_get
        requests.post = original_post


def _retry_on_disconnect(max_retries=MAX_RETRIES, base_backoff=BASE_BACKOFF_SECONDS):
    """Retry with exponential backoff on connection errors."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (ConnectionError, OSError) as exc:
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

        with _requests_default_timeout():
            frame = ak.fund_etf_spot_em()
        frame["source_endpoint"] = "fund_etf_spot_em"
        frame["provider"] = self.provider
        frame["updated_at"] = datetime.now(UTC)
        return frame

    @_retry_on_disconnect(max_retries=1, base_backoff=2)
    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        import akshare as ak

        code = symbol.split(".")[0]
        with _requests_default_timeout():
            frame = ak.fund_etf_hist_em(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
        frame["source_endpoint"] = "fund_etf_hist_em"
        frame["symbol"] = symbol
        frame["provider"] = self.provider
        frame["updated_at"] = datetime.now(UTC)
        return frame
