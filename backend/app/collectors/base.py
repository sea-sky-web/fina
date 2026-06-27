from abc import ABC, abstractmethod

import pandas as pd


class EtfDataCollector(ABC):
    provider: str

    @abstractmethod
    def fetch_etf_universe(self) -> pd.DataFrame:
        """Fetch ETF universe from the provider."""

    @abstractmethod
    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch daily OHLCV bars for one ETF."""
