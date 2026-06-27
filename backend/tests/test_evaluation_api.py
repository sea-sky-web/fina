from datetime import date, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.factor_service import list_factor_scores, rebuild_factors


def _evaluation_daily_frame() -> pd.DataFrame:
    start = date(2025, 1, 1)
    rows = []
    for offset in range(130):
        current_date = start + timedelta(days=offset)
        for index in range(10):
            close = 100 + offset * (index + 1)
            rows.append(
                {
                    "symbol": f"ETF{index}.SH",
                    "date": current_date,
                    "close": close,
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                    "volume": 1000 + index * 100,
                    "amount": 1_000_000 + offset * 1000 + index * 20_000,
                    "factor": 1.0,
                    "provider": "test",
                }
            )
    return pd.DataFrame(rows)


def _evaluation_basic_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": f"ETF{index}.SH",
                "name": f"测试ETF{index}",
                "index_name": "测试指数",
            }
            for index in range(10)
        ]
    )


def test_rebuild_factors_writes_processed_scores(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    _evaluation_daily_frame().to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)
    _evaluation_basic_frame().to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)

    result = rebuild_factors()
    scores = list_factor_scores(factor_name="momentum_60d", processed=True)

    assert (settings.clean_dir / "factors_processed.parquet").exists()
    assert result["processed_rows"] > 0
    assert len(scores) == 10
    assert scores[0].rank == 1
    assert scores[0].percentile > scores[-1].percentile


def test_evaluation_api_returns_factor_and_pool_reports(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    _evaluation_daily_frame().to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)
    _evaluation_basic_frame().to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)
    rebuild_factors()

    client = TestClient(app)
    report_response = client.get("/api/evaluation/momentum_60d/report?horizons=1,5,20")
    pool_response = client.get("/api/evaluation/pool-report?horizons=1,5,20")

    assert report_response.status_code == 200
    report = report_response.json()
    assert report["factor_name"] == "momentum_60d"
    assert report["ic"]["num_periods"] > 0
    assert "20" in report["quantile_returns"]
    assert report["correlations"]["factor_names"]
    assert report["overall_verdict"] in {"可用", "待观察", "不推荐单独使用"}

    assert pool_response.status_code == 200
    pool = pool_response.json()
    assert len(pool["individual_reports"]) >= 1
    assert pool["correlation_matrix"]["factor_names"]
    assert pool["recommendations"]
