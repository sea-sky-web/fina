from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_monitoring_report_api_returns_checks(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    client = TestClient(app)

    response = client.get("/api/monitoring/report")

    assert response.status_code == 200
    payload = response.json()
    assert "generated_at" in payload
    assert payload["checks"]
    assert {check["key"] for check in payload["checks"]} >= {
        "data",
        "factor_pool",
        "market_regime",
    }
