from datetime import UTC, datetime

import pandas as pd


def infer_exchange(code: str) -> str:
    if code.startswith(("51", "52", "56", "58")):
        return "SH"
    if code.startswith(("15", "16", "18")):
        return "SZ"
    return "UNKNOWN"


def normalize_symbol(code: str) -> str:
    exchange = infer_exchange(code)
    return f"{code}.{exchange}" if exchange != "UNKNOWN" else code


def normalize_etf_spot(frame: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    now = datetime.now(UTC)
    required = ["代码", "名称"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"AKShare ETF spot data missing columns: {missing}")

    data = frame.copy()
    for column in ["最新价", "涨跌幅", "成交量", "成交额"]:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")

    sort_column = "成交额" if "成交额" in data.columns else "成交量"
    data = data.sort_values(sort_column, ascending=False).head(limit).copy()
    data["code"] = data["代码"].astype(str).str.zfill(6)
    data["exchange"] = data["code"].map(infer_exchange)
    data["symbol"] = data["code"].map(normalize_symbol)

    normalized = pd.DataFrame(
        {
            "symbol": data["symbol"],
            "code": data["code"],
            "exchange": data["exchange"],
            "name": data["名称"].astype(str),
            "full_name": None,
            "index_code": None,
            "index_name": None,
            "manager": None,
            "list_date": pd.NaT,
            "latest_price": data.get("最新价"),
            "pct_chg": data.get("涨跌幅"),
            "volume": data.get("成交量"),
            "amount": data.get("成交额"),
            "status": "active",
            "provider": "akshare",
            "updated_at": now,
        }
    )
    return normalized.reset_index(drop=True)


def normalize_etf_daily(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    now = datetime.now(UTC)
    if "日期" in frame.columns:
        column_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "涨跌额": "change",
            "涨跌幅": "pct_chg",
            "成交量": "volume",
            "成交额": "amount",
        }
    else:
        column_map = {
            "date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "amount",
        }

    required = ["date", "open", "high", "low", "close"]
    available_after_rename = {column_map.get(column, column) for column in frame.columns}
    missing = [column for column in required if column not in frame.columns]
    missing = [column for column in required if column not in available_after_rename]
    if missing:
        raise ValueError(f"AKShare ETF daily data for {symbol} missing columns: {missing}")

    data = frame.copy()
    data = data.rename(columns=column_map)
    data["date"] = pd.to_datetime(data["date"]).dt.date
    for column in ["open", "high", "low", "close", "change", "pct_chg", "volume", "amount"]:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")

    data["symbol"] = symbol
    data["pre_close"] = data["close"].shift(1)
    data["factor"] = 1.0
    data["provider"] = "akshare"
    data["updated_at"] = now

    columns = [
        "symbol",
        "date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "volume",
        "amount",
        "factor",
        "provider",
        "updated_at",
    ]
    return data.reindex(columns=columns).reset_index(drop=True)
