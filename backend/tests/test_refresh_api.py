from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.v1 import refresh as refresh_api
from app.main import app
from app.models import RefreshResult
from app.services import refresh_service


def test_refresh_endpoint_returns_refresh_result(monkeypatch) -> None:
    def fake_refresh_top_etfs(
        limit: int,
        lookback_days: int,
        *,
        rebuild_factor_data: bool,
    ) -> RefreshResult:
        assert rebuild_factor_data is True
        return RefreshResult(
            ok=True,
            message=f"limit={limit}, lookback_days={lookback_days}",
            selected_rows=limit,
            daily_rows=123,
            factor_rows=456,
            refreshed_at=datetime(2026, 5, 22, tzinfo=UTC),
        )

    monkeypatch.setattr(refresh_api, "refresh_top_etfs", fake_refresh_top_etfs)
    client = TestClient(app)

    response = client.post("/api/refresh/top-etfs?limit=10&lookback_days=365")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["selected_rows"] == 10
    assert response.json()["factor_rows"] == 456


def test_refresh_service_rebuilds_factors(monkeypatch) -> None:
    def fake_collect_top_etfs(limit: int, lookback_days: int) -> dict[str, object]:
        return {
            "provider": "akshare",
            "collected_at": "2026-05-22T10:00:00+00:00",
            "last_attempt_status": "ok",
            "selected_rows": limit,
            "daily_rows": 123,
            "failures": [],
        }

    def fake_rebuild_factors() -> dict[str, object]:
        return {
            "processed_rows": 456,
            "latest_date": "2026-05-22",
        }

    monkeypatch.setattr(refresh_service, "collect_top_etfs", fake_collect_top_etfs)
    monkeypatch.setattr(refresh_service, "rebuild_factors", fake_rebuild_factors)

    result = refresh_service.refresh_top_etfs(limit=10, lookback_days=365)

    assert result.ok is True
    assert result.factor_rows == 456
    assert result.factor_latest_date.isoformat() == "2026-05-22"
