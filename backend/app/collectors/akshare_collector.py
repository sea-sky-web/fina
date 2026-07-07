from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
from typing import Any

import pandas as pd

from app.collectors.base import EtfDataCollector

DEFAULT_REQUEST_TIMEOUT_SECONDS = 12


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


class AkshareEtfCollector(EtfDataCollector):
    provider = "akshare"

    def fetch_etf_universe(self) -> pd.DataFrame:
        import akshare as ak

        with _requests_default_timeout():
            frame = ak.fund_etf_spot_em()
        frame["source_endpoint"] = "fund_etf_spot_em"
        frame["provider"] = self.provider
        frame["updated_at"] = datetime.now(UTC)
        return frame

    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        import akshare as ak

        code = symbol.split(".")[0]
        sina_symbol = f"{symbol.split('.')[1].lower()}{code}" if "." in symbol else code
        try:
            with _requests_default_timeout():
                frame = ak.fund_etf_hist_em(
                    symbol=code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="hfq",
                )
            frame["source_endpoint"] = "fund_etf_hist_em"
        except Exception as em_exc:
            try:
                with _requests_default_timeout():
                    frame = ak.fund_etf_hist_sina(symbol=sina_symbol)
                frame["date"] = pd.to_datetime(frame["date"])
                frame = frame[
                    (frame["date"] >= pd.to_datetime(start_date))
                    & (frame["date"] <= pd.to_datetime(end_date))
                ].copy()
            except Exception as sina_exc:
                raise RuntimeError(
                    f"ETF daily fetch failed for {symbol}; "
                    f"eastmoney={em_exc}; sina={sina_exc}"
                ) from sina_exc
            frame["source_endpoint"] = "fund_etf_hist_sina"
        frame["symbol"] = symbol
        frame["provider"] = self.provider
        frame["updated_at"] = datetime.now(UTC)
        return frame
