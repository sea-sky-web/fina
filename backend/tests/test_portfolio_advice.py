from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models import PortfolioAdviceRequest, PortfolioHoldingInput
from app.services.portfolio_advice_service import build_portfolio_advice


def _write_fixture(tmp_path) -> None:
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range("2025-12-01", periods=150, freq="B").date
    rows = []
    configs = {
        "510300.SH": ("沪深300ETF", 1.00, 1.12, 300_000_000),
        "AAA.SH": ("半导体ETF", 1.00, 1.55, 500_000_000),
        "BBB.SH": ("医药ETF", 1.00, 0.90, 50_000_000),
    }
    for symbol, (_, start, end, amount) in configs.items():
        closes = pd.Series(range(len(dates)), dtype="float64")
        closes = start + (end - start) * closes / max(len(dates) - 1, 1)
        for idx, day in enumerate(dates):
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "close": float(closes.iloc[idx]),
                    "amount": float(amount + idx * 1_000_000),
                }
            )
    pd.DataFrame(rows).to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)
    pd.DataFrame(
        [
            {"symbol": symbol, "name": name, "index_name": None}
            for symbol, (name, *_rest) in configs.items()
        ]
    ).to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)

    rotation_input_path = tmp_path / "rotation_inputs.csv"
    pd.DataFrame(
        [
            {
                "symbol": "",
                "theme": "半导体芯片",
                "etf_type": "行业",
                "boom_status": "上行",
                "boom_score": 85,
                "valuation_percentile": 35,
                "structure_score": 70,
                "notes": "国产替代景气修复",
            },
            {
                "symbol": "",
                "theme": "医药医疗",
                "etf_type": "行业",
                "boom_status": "下行",
                "boom_score": 35,
                "valuation_percentile": 25,
                "structure_score": 65,
                "notes": "政策仍需观察",
            },
        ]
    ).to_csv(rotation_input_path, index=False)
    settings.rotation_input_path = rotation_input_path


def test_portfolio_advice_compares_current_and_target_weights(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_fixture(tmp_path)

    report = build_portfolio_advice(
        PortfolioAdviceRequest(
            holdings=[PortfolioHoldingInput(symbol="BBB.SH", weight=0.20)],
            target_count=1,
            universe_limit=3,
            min_trade_weight=0.01,
        )
    )

    by_symbol = {item.symbol: item for item in report.advice}
    assert report.target_symbols == ["AAA.SH"]
    assert by_symbol["AAA.SH"].action == "新增配置候选"
    assert by_symbol["AAA.SH"].target_weight > 0
    assert by_symbol["BBB.SH"].action == "减仓候选"
    assert by_symbol["BBB.SH"].target_weight == 0
    assert report.estimated_turnover > 0
    assert any("不构成投资建议" in note for note in report.data_notes)


def test_portfolio_advice_api(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_fixture(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/portfolio/advice",
        json={
            "holdings": [{"symbol": "BBB.SH", "weight": 0.20}],
            "target_count": 1,
            "universe_limit": 3,
            "min_trade_weight": 0.01,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_symbols"] == ["AAA.SH"]
    assert {item["action"] for item in payload["advice"]} >= {
        "新增配置候选",
        "减仓候选",
    }
