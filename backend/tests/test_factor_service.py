from datetime import date, timedelta

import pandas as pd

from app.core.config import settings
from app.services.factor_service import list_factor_scores, rebuild_factors


def _daily_frame() -> pd.DataFrame:
    start = date(2026, 1, 1)
    rows = []
    for offset in range(65):
        current_date = start + timedelta(days=offset)
        rows.append(
            {
                "symbol": "AAA.SH",
                "date": current_date,
                "close": 100 + offset,
                "open": 100 + offset,
                "high": 100 + offset,
                "low": 100 + offset,
                "volume": 1000,
                "amount": 1000 + offset * 12,
                "factor": 1.0,
                "provider": "test",
            }
        )
        rows.append(
            {
                "symbol": "BBB.SZ",
                "date": current_date,
                "close": 100 + offset * 0.5,
                "open": 100 + offset * 0.5,
                "high": 100 + offset * 0.5,
                "low": 100 + offset * 0.5,
                "volume": 1000,
                "amount": 900 + offset * 4,
                "factor": 1.0,
                "provider": "test",
            }
        )
    return pd.DataFrame(rows)


def test_rebuild_factors_writes_ranked_scores(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    _daily_frame().to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)
    pd.DataFrame(
        [
            {"symbol": "AAA.SH", "name": "沪深300ETF", "index_name": None},
            {"symbol": "BBB.SZ", "name": "创业板ETF", "index_name": None},
        ]
    ).to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)

    result = rebuild_factors()
    scores = list_factor_scores()

    assert result["symbols"] == 2
    assert len(scores) == 2
    assert scores[0].symbol == "AAA.SH"
    assert scores[0].rank == 1
    assert scores[0].lookback_days == 60
    assert scores[0].factor_value > scores[1].factor_value
    assert scores[0].theme == "宽基指数"


def test_volatility_factor_is_computed(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    _daily_frame().to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)
    pd.DataFrame(
        [
            {"symbol": "AAA.SH", "name": "沪深300ETF", "index_name": None},
            {"symbol": "BBB.SZ", "name": "创业板ETF", "index_name": None},
        ]
    ).to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)

    result = rebuild_factors()
    vol_scores = list_factor_scores(factor_name="volatility_30d")

    factor_names = {item["factor_name"] for item in result["factors"]}
    assert "volatility_30d" in factor_names
    assert "risk_adjusted_return_60d" in factor_names
    assert "liquidity_stability_20d" in factor_names
    assert "trend_strength_20_60d" in factor_names
    assert len(vol_scores) == 2


def test_lower_volatility_gets_better_rank(
    monkeypatch,
    tmp_path,
) -> None:
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
    vol_scores = list_factor_scores(factor_name="volatility_30d")

    assert vol_scores[0].symbol == "LOW.SH"
    assert vol_scores[0].rank == 1
    assert vol_scores[0].percentile > vol_scores[1].percentile
