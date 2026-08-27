"""实时行情直取 — 不落盘,每次调用都现场向 AKShare 要数据。

v1 只做"拿到当下决策要用的数据",不做 provider 抽象、不做 raw/clean 落盘。
回测用的历史数据缓存是单独的 scripts/fetch_backtest_history.py，与这里无关。
"""
from __future__ import annotations

import time
from functools import wraps
from typing import Any

import pandas as pd

DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 3


def _retry(max_retries: int = DEFAULT_RETRIES, base_backoff: float = DEFAULT_BACKOFF_SECONDS):
    def decorator(func):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:  # AKShare 底层抓取失败的异常类型不固定
                    last_exc = exc
                    if attempt < max_retries:
                        time.sleep(base_backoff * (2**attempt))
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


def infer_exchange(code: str) -> str | None:
    if code.startswith(("51", "52", "56", "58")):
        return "SH"
    if code.startswith(("15", "16", "18")):
        return "SZ"
    return None


def normalize_symbol(code: str) -> str | None:
    code = str(code).strip()
    if len(code) != 6 or not code.isdigit():
        return None
    exchange = infer_exchange(code)
    return f"{code}.{exchange}" if exchange else None


@_retry()
def fetch_etf_universe() -> pd.DataFrame:
    """全市场ETF现价快照：symbol, name, close, amount(今日成交额)。"""
    import akshare as ak

    frame = ak.fund_etf_spot_em()
    if frame is None or frame.empty:
        raise ValueError("AKShare 返回空的 ETF 列表")
    frame = frame.rename(columns={"代码": "code", "名称": "name", "最新价": "close", "成交额": "amount"})
    frame["symbol"] = frame["code"].map(normalize_symbol)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    return frame.dropna(subset=["symbol"])[["symbol", "code", "name", "close", "amount"]]


MAX_SINGLE_DAY_RETURN = 0.22  # 超过这个单日涨跌幅视为疑似复权/数据错位，整条丢弃


@_retry(max_retries=2, base_backoff=2)
def fetch_daily_bars(symbol: str, lookback_trading_days: int = 90) -> pd.DataFrame:
    """单只ETF最近 lookback_trading_days 个交易日的日线：symbol, date, close, amount。

    注：本机网络环境下 AKShare 的东方财富历史K线接口(fund_etf_hist_em，走
    push2his.eastmoney.com)会被连接直接断开，实测新浪财经接口(fund_etf_hist_sina)
    可正常访问，所以这里用新浪源。新浪接口返回的是全量历史，这里只取尾部所需窗口。
    """
    import akshare as ak

    code, exchange = symbol.split(".")
    sina_symbol = f"{exchange.lower()}{code}"
    frame = ak.fund_etf_hist_sina(symbol=sina_symbol)
    if frame is None or frame.empty:
        raise ValueError(f"AKShare 返回空的日线数据: {symbol}")
    frame = frame.rename(columns={"date": "date", "close": "close", "amount": "amount"})
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    frame["symbol"] = symbol
    frame = frame.dropna(subset=["close"]).sort_values("date").tail(lookback_trading_days)

    daily_return = frame["close"].pct_change().abs()
    if (daily_return > MAX_SINGLE_DAY_RETURN).any():
        raise ValueError(f"{symbol} 日线数据出现单日涨跌幅超过{MAX_SINGLE_DAY_RETURN:.0%}，疑似数据错位")

    return frame[["symbol", "date", "close", "amount"]]
