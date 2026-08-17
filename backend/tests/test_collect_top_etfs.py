import json
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from app.collectors.akshare_collector import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    AkshareEtfCollector,
)
from app.core.config import settings
from app.jobs.collect_top_etfs import collect_top_etfs
from app.normalizers.akshare import normalize_etf_spot, normalize_symbol


def _spot_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "代码": "510300",
                "名称": "沪深300ETF",
                "最新价": 4.8,
                "涨跌幅": 1.2,
                "成交量": 10,
                "成交额": 1000,
            },
            {
                "代码": "159915",
                "名称": "创业板ETF",
                "最新价": 3.8,
                "涨跌幅": -0.5,
                "成交量": 20,
                "成交额": 900,
            },
        ]
    )


def _daily_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-05-20",
                "open": 4.7,
                "high": 4.9,
                "low": 4.6,
                "close": 4.8,
                "volume": 10,
                "amount": 1000,
            },
            {
                "date": "2026-05-21",
                "open": 4.8,
                "high": 5.0,
                "low": 4.7,
                "close": 4.9,
                "volume": 12,
                "amount": 1200,
            },
        ]
    )


def test_normalize_symbol_supports_shanghai_52_prefix() -> None:
    assert normalize_symbol("520500") == "520500.SH"


def test_normalize_etf_spot_keeps_top_n_when_quote_timestamps_exist() -> None:
    frame = _spot_frame()
    frame.index = [10, 20]
    frame["数据日期"] = "2026-06-30"
    frame["更新时间"] = "2026-06-30 15:00:00+08:00"

    normalized = normalize_etf_spot(frame, limit=1)

    assert len(normalized) == 1
    assert normalized["symbol"].tolist() == ["510300.SH"]
    assert normalized["spot_date"].iloc[0].isoformat() == "2026-06-30"


def test_akshare_collector_applies_default_request_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_timeouts: list[int] = []

    def fake_get(*args, **kwargs):  # noqa: ANN002, ANN003
        captured_timeouts.append(kwargs["timeout"])
        return SimpleNamespace()

    def fake_em(
        symbol: str, period: str, start_date: str, end_date: str, adjust: str
    ) -> pd.DataFrame:
        import requests

        requests.get("https://example.test/daily")
        return _daily_frame()

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(fund_etf_hist_em=fake_em),
    )

    frame = AkshareEtfCollector().fetch_daily_bars("510300.SH", "20260520", "20260521")

    assert frame["source_endpoint"].tolist() == ["fund_etf_hist_em", "fund_etf_hist_em"]
    assert captured_timeouts == [DEFAULT_REQUEST_TIMEOUT_SECONDS]


def test_collect_top_etfs_writes_clean_outputs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        "app.jobs.collect_top_etfs.universe_path",
        lambda: tmp_path / "config" / "strategy_universe.csv",
    )
    monkeypatch.setattr(AkshareEtfCollector, "fetch_etf_universe", lambda self: _spot_frame())
    monkeypatch.setattr(
        AkshareEtfCollector,
        "fetch_daily_bars",
        lambda self, symbol, start_date, end_date: _daily_frame(),
    )

    manifest = collect_top_etfs(limit=1, lookback_days=365)

    etf_basic = pd.read_parquet(settings.clean_dir / "etf_basic.parquet")
    etf_daily = pd.read_parquet(settings.clean_dir / "etf_daily.parquet")
    assert manifest["selected_rows"] == 1
    assert manifest["daily_rows"] == 2
    assert etf_basic["symbol"].tolist() == ["510300.SH"]
    assert len(etf_daily) == 2


def test_collect_top_etfs_keeps_previous_clean_data_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        "app.jobs.collect_top_etfs.universe_path",
        lambda: tmp_path / "config" / "strategy_universe.csv",
    )
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    old_basic = pd.DataFrame([{"symbol": "OLD.SH", "amount": 1.0}])
    old_daily = pd.DataFrame([{"symbol": "OLD.SH", "date": "2026-05-21", "close": 1.0}])
    old_basic.to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)
    old_daily.to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)

    monkeypatch.setattr(AkshareEtfCollector, "fetch_etf_universe", lambda self: _spot_frame())

    def fail_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(AkshareEtfCollector, "fetch_daily_bars", fail_daily)

    with pytest.raises(RuntimeError):
        collect_top_etfs(limit=1, lookback_days=365)

    etf_basic = pd.read_parquet(settings.clean_dir / "etf_basic.parquet")
    etf_daily = pd.read_parquet(settings.clean_dir / "etf_daily.parquet")
    manifest = json.loads((settings.clean_dir / "collection_manifest.json").read_text())
    assert etf_basic["symbol"].tolist() == ["OLD.SH"]
    assert etf_daily["symbol"].tolist() == ["OLD.SH"]
    assert manifest["last_attempt_status"] == "error"
    assert manifest["failures"][0]["symbol"] == "510300.SH"


def test_collect_top_etfs_reuses_cached_universe_when_spot_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        "app.jobs.collect_top_etfs.universe_path",
        lambda: tmp_path / "config" / "strategy_universe.csv",
    )
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    cached_basic = pd.DataFrame(
        [
            {
                "symbol": "510300.SH",
                "code": "510300",
                "exchange": "SH",
                "name": "沪深300ETF",
                "amount": 1000.0,
                "provider": "akshare",
            }
        ]
    )
    cached_basic.to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)

    def fail_spot(self) -> pd.DataFrame:
        raise RuntimeError("ssl eof")

    monkeypatch.setattr(AkshareEtfCollector, "fetch_etf_universe", fail_spot)
    monkeypatch.setattr(
        AkshareEtfCollector,
        "fetch_daily_bars",
        lambda self, symbol, start_date, end_date: _daily_frame(),
    )

    manifest = collect_top_etfs(limit=1, lookback_days=365)

    etf_basic = pd.read_parquet(settings.clean_dir / "etf_basic.parquet")
    etf_daily = pd.read_parquet(settings.clean_dir / "etf_daily.parquet")
    assert manifest["last_attempt_status"] == "degraded"
    assert manifest["spot_source"] == "cached_clean_etf_basic"
    assert etf_basic["symbol"].tolist() == ["510300.SH"]
    assert len(etf_daily) == 2


def test_collect_top_etfs_reuses_raw_spot_cache_before_clean_universe(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        "app.jobs.collect_top_etfs.universe_path",
        lambda: tmp_path / "config" / "strategy_universe.csv",
    )
    raw_spot_path = settings.raw_dir / "akshare" / "etf_spot" / "date=20260528" / "part.parquet"
    raw_spot_path.parent.mkdir(parents=True, exist_ok=True)
    _spot_frame().to_parquet(raw_spot_path, index=False)

    def fail_spot(self) -> pd.DataFrame:
        raise RuntimeError("ssl eof")

    monkeypatch.setattr(AkshareEtfCollector, "fetch_etf_universe", fail_spot)
    monkeypatch.setattr(
        AkshareEtfCollector,
        "fetch_daily_bars",
        lambda self, symbol, start_date, end_date: _daily_frame(),
    )

    manifest = collect_top_etfs(limit=2, lookback_days=365)

    etf_basic = pd.read_parquet(settings.clean_dir / "etf_basic.parquet")
    assert manifest["last_attempt_status"] == "degraded"
    assert manifest["spot_source"] == "cached_raw_etf_spot"
    assert etf_basic["symbol"].tolist() == ["510300.SH", "159915.SZ"]


def test_collect_top_etfs_reuses_cached_daily_when_daily_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        "app.jobs.collect_top_etfs.universe_path",
        lambda: tmp_path / "config" / "strategy_universe.csv",
    )
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    cached_daily = pd.DataFrame(
        [
            {
                "symbol": "510300.SH",
                "date": "2026-05-21",
                "open": 4.8,
                "high": 4.9,
                "low": 4.7,
                "close": 4.8,
                "volume": 10,
                "amount": 1000,
                "factor": 1.0,
                "provider": "akshare",
            }
        ]
    )
    cached_daily.to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)

    monkeypatch.setattr(AkshareEtfCollector, "fetch_etf_universe", lambda self: _spot_frame())

    def fail_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise RuntimeError("daily ssl eof")

    monkeypatch.setattr(AkshareEtfCollector, "fetch_daily_bars", fail_daily)

    manifest = collect_top_etfs(limit=1, lookback_days=365)

    etf_daily = pd.read_parquet(settings.clean_dir / "etf_daily.parquet")
    assert manifest["last_attempt_status"] == "degraded"
    assert manifest["daily_rows"] == 1
    assert etf_daily["symbol"].tolist() == ["510300.SH"]


def test_collect_top_etfs_writes_partial_daily_when_some_symbols_have_no_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        "app.jobs.collect_top_etfs.universe_path",
        lambda: tmp_path / "config" / "strategy_universe.csv",
    )
    monkeypatch.setattr(AkshareEtfCollector, "fetch_etf_universe", lambda self: _spot_frame())

    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        if symbol == "159915.SZ":
            raise RuntimeError("daily unavailable")
        return _daily_frame()

    monkeypatch.setattr(AkshareEtfCollector, "fetch_daily_bars", fetch_daily)

    manifest = collect_top_etfs(limit=2, lookback_days=365)

    etf_basic = pd.read_parquet(settings.clean_dir / "etf_basic.parquet")
    etf_daily = pd.read_parquet(settings.clean_dir / "etf_daily.parquet")
    assert manifest["last_attempt_status"] == "degraded"
    assert manifest["selected_rows"] == 2
    assert manifest["daily_missing_symbols"] == ["159915.SZ"]
    assert etf_basic["symbol"].tolist() == ["510300.SH", "159915.SZ"]
    assert etf_daily["symbol"].unique().tolist() == ["510300.SH"]


def test_collect_top_etfs_uses_same_day_raw_daily_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        "app.jobs.collect_top_etfs.universe_path",
        lambda: tmp_path / "config" / "strategy_universe.csv",
    )
    monkeypatch.setattr(AkshareEtfCollector, "fetch_etf_universe", lambda self: _spot_frame())

    raw_daily_root = settings.raw_dir / "akshare" / "etf_daily"
    for symbol in ["510300.SH", "159915.SZ"]:
        raw_daily_path = raw_daily_root / f"symbol={symbol}" / "date=20260528" / "part.parquet"
        raw_daily_path.parent.mkdir(parents=True, exist_ok=True)
        _daily_frame().to_parquet(raw_daily_path, index=False)

    class FixedDatetime:
        @staticmethod
        def now(tz=None):  # noqa: ANN001
            return pd.Timestamp("2026-05-28T12:00:00Z").to_pydatetime()

    monkeypatch.setattr("app.jobs.collect_top_etfs.datetime", FixedDatetime)

    def fail_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise AssertionError("same-day raw daily cache should be used before live collection")

    monkeypatch.setattr(AkshareEtfCollector, "fetch_daily_bars", fail_daily)

    manifest = collect_top_etfs(limit=2, lookback_days=365)

    assert manifest["selected_rows"] == 2
    assert manifest["daily_rows"] == 4
    assert manifest["last_attempt_status"] == "ok"
