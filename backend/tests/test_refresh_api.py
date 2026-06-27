from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.v1 import refresh as refresh_api
from app.main import app
from app.models import RefreshResult


def test_refresh_endpoint_returns_refresh_result(monkeypatch) -> None:
    def fake_refresh_top_etfs(limit: int, lookback_days: int) -> RefreshResult:
        return RefreshResult(
            ok=True,
            message=f"limit={limit}, lookback_days={lookback_days}",
            selected_rows=limit,
            daily_rows=123,
            refreshed_at=datetime(2026, 5, 22, tzinfo=UTC),
        )

    monkeypatch.setattr(refresh_api, "refresh_top_etfs", fake_refresh_top_etfs)
    client = TestClient(app)

    response = client.post("/api/refresh/top-etfs?limit=10&lookback_days=365")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["selected_rows"] == 10
