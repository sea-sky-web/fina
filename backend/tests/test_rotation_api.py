from datetime import date

from fastapi.testclient import TestClient

from app.api.v1 import rotation as rotation_api
from app.main import app
from app.services.rotation_service import RotationReport, RotationScore


def test_rotation_report_endpoint(monkeypatch) -> None:
    def fake_build_rotation_report(*, top_n: int) -> RotationReport:
        assert top_n == 3
        score = RotationScore(
            symbol="AAA.SH",
            name="半导体ETF",
            theme="半导体芯片",
            etf_type="行业",
            date=date(2026, 6, 30),
            total_score=82.0,
            boom_score=85.0,
            momentum_score=80.0,
            valuation_score=65.0,
            structure_score=70.0,
            liquidity_score=75.0,
            risk_score=68.0,
            boom_status="上行",
            valuation_percentile=35.0,
            state="景气上行 + 动量确认",
            action="主线候选",
            returns={"1m": 0.03, "3m": 0.12, "6m": 0.18, "relative_3m": 0.04},
            risk_notes=["未触发核心风险阈值。"],
            drivers=["景气评分较高"],
        )
        return RotationReport(
            date=date(2026, 6, 30),
            rankings=[score],
            pools={"core_candidates": [score], "watchlist": [], "avoid": []},
            data_notes=["demo"],
        )

    monkeypatch.setattr(rotation_api, "build_rotation_report", fake_build_rotation_report)
    client = TestClient(app)

    response = client.get("/api/rotation/report?top_n=3")

    assert response.status_code == 200
    payload = response.json()
    assert payload["radar_date"] == "2026-06-30"
    assert payload["rankings"][0]["symbol"] == "AAA.SH"
    assert payload["rankings"][0]["state"] == "景气上行 + 动量确认"
    assert payload["pools"]["core_candidates"] == ["AAA.SH"]
