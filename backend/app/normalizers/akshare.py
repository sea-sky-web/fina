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
    numeric_columns = [
        "最新价",
        "IOPV实时估值",
        "基金折价率",
        "涨跌额",
        "涨跌幅",
        "成交量",
        "成交额",
        "开盘价",
        "最高价",
        "最低价",
        "昨收",
        "振幅",
        "换手率",
        "量比",
        "最新份额",
        "流通市值",
        "总市值",
    ]
    for column in numeric_columns:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    sort_column = "成交额" if "成交额" in data.columns else "成交量"
    data = data.sort_values(sort_column, ascending=False).head(limit).copy()
    spot_date = (
        pd.to_datetime(data["数据日期"], errors="coerce").dt.date
        if "数据日期" in data.columns
        else None
    )
    quote_updated_at = (
        pd.to_datetime(data["更新时间"], errors="coerce", utc=True)
        if "更新时间" in data.columns
        else None
    )
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
            "iopv": data.get("IOPV实时估值"),
            "premium_discount_rate": data.get("基金折价率"),
            "pct_chg": data.get("涨跌幅"),
            "change": data.get("涨跌额"),
            "open": data.get("开盘价"),
            "high": data.get("最高价"),
            "low": data.get("最低价"),
            "pre_close": data.get("昨收"),
            "amplitude": data.get("振幅"),
            "volume": data.get("成交量"),
            "amount": data.get("成交额"),
            "turnover_rate": data.get("换手率"),
            "volume_ratio": data.get("量比"),
            "latest_share": data.get("最新份额"),
            "circulating_market_value": data.get("流通市值"),
            "total_market_value": data.get("总市值"),
            "spot_date": spot_date,
            "quote_updated_at": quote_updated_at,
            "status": "active",
            "provider": "akshare",
            "source_endpoint": data.get("source_endpoint", "fund_etf_spot_em"),
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
            "振幅": "amplitude",
            "换手率": "turnover_rate",
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
    for column in [
        "open",
        "high",
        "low",
        "close",
        "change",
        "pct_chg",
        "volume",
        "amount",
        "amplitude",
        "turnover_rate",
    ]:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")

    data["symbol"] = symbol
    data["pre_close"] = data["close"].shift(1)
    data["factor"] = 1.0
    data["provider"] = "akshare"
    data["updated_at"] = now

    # 数据质量校验：源一致性
    if "source_endpoint" in data.columns:
        endpoints = data["source_endpoint"].dropna().unique()
        if len(endpoints) > 1:
            raise ValueError(
                f"ETF {symbol}: mixed source endpoints {list(endpoints)}. "
                f"This will corrupt price continuity."
            )

    # 数据质量校验：单日涨跌幅上限（A股ETF涨跌停10-20%，留2%容差）
    MAX_DAILY_RETURN = 0.22
    if len(data) > 1:
        daily_ret = (data["close"] / data["pre_close"] - 1).iloc[1:]
        n_bad = int((daily_ret.abs() > MAX_DAILY_RETURN).sum())
        if n_bad > 0:
            bad_dates = data.loc[daily_ret[daily_ret.abs() > MAX_DAILY_RETURN].index, "date"].tolist()
            raise ValueError(
                f"ETF {symbol}: {n_bad} daily returns exceed +/-{MAX_DAILY_RETURN:.0%}. "
                f"Dates: {bad_dates[:5]}. Likely mixed price adjustment sources."
            )

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
        "amplitude",
        "turnover_rate",
        "factor",
        "provider",
        "source_endpoint",
        "updated_at",
    ]
    return data.reindex(columns=columns).reset_index(drop=True)
