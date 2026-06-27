from datetime import UTC, datetime

import pandas as pd

from app.collectors.base import EtfDataCollector


class AkshareEtfCollector(EtfDataCollector):
    provider = "akshare"

    def fetch_etf_universe(self) -> pd.DataFrame:
        import akshare as ak

        frame = ak.fund_etf_spot_em()
        frame["provider"] = self.provider
        frame["updated_at"] = datetime.now(UTC)
        return frame

    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        import akshare as ak

        code = symbol.split(".")[0]
        if code.startswith("52"):
            raise RuntimeError("52-prefix ETF daily endpoint is currently unstable")

        sina_symbol = f"{symbol.split('.')[1].lower()}{code}" if "." in symbol else code
        try:
            frame = ak.fund_etf_hist_sina(symbol=sina_symbol)
            frame["date"] = pd.to_datetime(frame["date"])
            frame = frame[
                (frame["date"] >= pd.to_datetime(start_date))
                & (frame["date"] <= pd.to_datetime(end_date))
            ].copy()
            frame["source_endpoint"] = "fund_etf_hist_sina"
        except Exception:
            frame = ak.fund_etf_hist_em(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="",
            )
            frame["source_endpoint"] = "fund_etf_hist_em"
        frame["symbol"] = symbol
        frame["provider"] = self.provider
        frame["updated_at"] = datetime.now(UTC)
        return frame
