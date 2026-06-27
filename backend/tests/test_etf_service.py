from app.core.config import settings
from app.services.etf_service import get_etf_daily, list_etfs


def test_etf_service_returns_empty_lists_without_clean_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.clean_dir.mkdir(parents=True, exist_ok=True)

    assert list_etfs() == []
    assert get_etf_daily("510300.SH") == []
