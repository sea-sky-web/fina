from datetime import date, timedelta

import pandas as pd
from fastapi.testclient import TestClient
from test_factor_service import _daily_frame

from app.core.config import settings
from app.main import app
from app.services.factor_service import rebuild_factors


def test_factors_api_returns_latest_scores(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    _daily_frame().to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)
    pd.DataFrame(
        [
            {"symbol": "AAA.SH", "name": "沪深300ETF", "index_name": None},
            {"symbol": "BBB.SZ", "name": "创业板ETF", "index_name": None},
        ]
    ).to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)
    rebuild_factors()

    client = TestClient(app)
    response = client.get("/api/factors?limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert payload[0]["factor_name"] == "momentum_60d"
    assert payload[0]["rank"] == 1


def test_factors_api_does_not_rebuild_on_get(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    _daily_frame().to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)

    client = TestClient(app)
    response = client.get("/api/factors?limit=2")

    assert response.status_code == 200
    assert response.json() == []
    assert not (settings.clean_dir / "factors.parquet").exists()


def test_factor_definitions_include_interpretation_metadata() -> None:
    client = TestClient(app)
    response = client.get("/api/factors/definitions")

    assert response.status_code == 200
    payload = response.json()
    momentum = next(item for item in payload if item["name"] == "momentum_60d")
    assert momentum["lookback_days"] == "60"
    assert momentum["direction"] == "higher_better"
    assert momentum["category"] == "return"
    assert momentum["format"] == "percent"
    assert momentum["interpretation"]


def _diagnostic_daily_frame() -> pd.DataFrame:
    start = date(2025, 1, 1)
    rows = []
    for offset in range(110):
        current_date = start + timedelta(days=offset)
        for index in range(5):
            symbol = f"ETF{index}.SH"
            close = 100 + offset * (index + 1)
            rows.append(
                {
                    "symbol": symbol,
                    "date": current_date,
                    "close": close,
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                    "volume": 1000 + index * 100,
                    "amount": 1_000_000 + offset * 1000 + index * 10_000,
                    "factor": 1.0,
                    "provider": "test",
                }
            )
    return pd.DataFrame(rows)


def _diagnostic_basic_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"symbol": f"ETF{index}.SH", "name": f"测试ETF{index}", "index_name": None}
            for index in range(5)
        ]
    )


def test_factor_diagnostics_returns_distribution_and_forward_return(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    _diagnostic_daily_frame().to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)
    _diagnostic_basic_frame().to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)
    rebuild_factors()

    client = TestClient(app)
    response = client.get("/api/factors/diagnostics?name=momentum_60d&horizon=5&limit=3")

    assert response.status_code == 200
    payload = response.json()
    assert payload["definition"]["name"] == "momentum_60d"
    assert payload["distribution"]["count"] == 5
    assert len(payload["top"]) == 3
    assert len(payload["bottom"]) == 3
    assert payload["top"][0]["rank"] == 1
    assert payload["forward_return"]["sample_count"] > 0
    assert payload["forward_return"]["top_mean"] > payload["forward_return"]["bottom_mean"]
    assert payload["stability"]["label"] in {"较稳定", "中等波动", "跳动较大"}


def test_factor_diagnostics_respects_lower_better_direction(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    start = date(2026, 1, 1)
    rows = []
    for offset in range(80):
        current_date = start + timedelta(days=offset)
        rows.append(
            {
                "symbol": "LOW.SH",
                "date": current_date,
                "close": 100 + offset * 0.1,
                "open": 100,
                "high": 101,
                "low": 99,
                "volume": 1000,
                "amount": 1000 + offset,
                "factor": 1.0,
                "provider": "test",
            }
        )
        rows.append(
            {
                "symbol": "HIGH.SZ",
                "date": current_date,
                "close": 100 + (offset % 2) * 10 + offset * 0.1,
                "open": 100,
                "high": 112,
                "low": 92,
                "volume": 1000,
                "amount": 1200 + offset * 3,
                "factor": 1.0,
                "provider": "test",
            }
        )
    pd.DataFrame(rows).to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)
    pd.DataFrame(
        [
            {"symbol": "LOW.SH", "name": "低波动ETF", "index_name": None},
            {"symbol": "HIGH.SZ", "name": "高波动ETF", "index_name": None},
        ]
    ).to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)
    rebuild_factors()

    client = TestClient(app)
    response = client.get("/api/factors/diagnostics?name=volatility_30d&limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["definition"]["direction"] == "lower_better"
    assert payload["top"][0]["symbol"] == "LOW.SH"
    assert payload["bottom"][0]["symbol"] == "HIGH.SZ"


def test_factor_diagnostics_handles_insufficient_forward_samples(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    _daily_frame().to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)
    pd.DataFrame(
        [
            {"symbol": "AAA.SH", "name": "沪深300ETF", "index_name": None},
            {"symbol": "BBB.SZ", "name": "创业板ETF", "index_name": None},
        ]
    ).to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)
    rebuild_factors()

    client = TestClient(app)
    response = client.get("/api/factors/diagnostics?name=momentum_60d&horizon=120")

    assert response.status_code == 200
    payload = response.json()
    assert payload["forward_return"]["sample_count"] == 0
    assert payload["forward_return"]["data_notes"]
