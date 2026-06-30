import json
from datetime import UTC, date, datetime

import pandas as pd
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.data_source_audit import audit_data_sources
from app.storage.parquet_store import write_parquet


def _write_clean_data(tmp_path, *, provider: str = "akshare") -> None:
    monkey_date = date.today()
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir(parents=True, exist_ok=True)
    (clean_dir / "collection_manifest.json").write_text(
        json.dumps(
            {
                "provider": provider,
                "collected_at": datetime.now(UTC).isoformat(),
                "last_attempt_status": "ok",
                "spot_source": "akshare_spot",
                "spot_source_endpoints": ["fund_etf_spot_em"],
                "daily_source_endpoints": ["fund_etf_hist_sina"],
                "selected_rows": 1,
                "daily_missing_symbols": [],
                "failures": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    write_parquet(
        pd.DataFrame(
            [
                {
                    "symbol": "510300.SH",
                    "code": "510300",
                    "exchange": "SH",
                    "name": "沪深300ETF",
                    "amount": 1000000.0,
                    "provider": provider,
                    "source_endpoint": "fund_etf_spot_em",
                    "updated_at": datetime.now(UTC),
                }
            ]
        ),
        clean_dir / "etf_basic.parquet",
    )
    write_parquet(
        pd.DataFrame(
            [
                {
                    "symbol": "510300.SH",
                    "date": monkey_date,
                    "close": 4.0,
                    "amount": 1000000.0,
                    "provider": provider,
                    "source_endpoint": "fund_etf_hist_sina",
                    "updated_at": datetime.now(UTC),
                }
            ]
        ),
        clean_dir / "etf_daily.parquet",
    )


def test_audit_data_sources_accepts_real_akshare_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_clean_data(tmp_path)

    audit = audit_data_sources()

    assert audit.ok is True
    assert audit.status == "ok"
    assert audit.provider == "akshare"
    assert audit.source_endpoints == ["fund_etf_hist_sina", "fund_etf_spot_em"]


def test_audit_data_sources_rejects_mock_provider(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_clean_data(tmp_path, provider="mock")

    audit = audit_data_sources()

    assert audit.ok is False
    assert audit.status == "error"
    assert any("non-production provider" in error for error in audit.errors)


def test_data_source_audit_endpoint(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_clean_data(tmp_path)
    client = TestClient(app)

    response = client.get("/api/data-sources/audit")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "akshare"
