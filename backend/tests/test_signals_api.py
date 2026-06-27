from datetime import UTC, date, datetime

import pandas as pd
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.signal_service import get_research_signal, list_research_signals


def _write_signal_fixture(tmp_path) -> None:
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    signal_date = date(2026, 4, 1)
    updated_at = datetime(2026, 4, 2, tzinfo=UTC)
    rows = [
        ("momentum_60d", 0.30, 1, 1.00),
        ("risk_adjusted_return_60d", 1.20, 2, 0.80),
        ("trend_strength_20_60d", 0.08, 3, 0.60),
        ("liquidity_stability_20d", 3.00, 4, 0.40),
        ("volatility_30d", 0.45, 9, 0.10),
        ("max_drawdown_60d", -0.18, 8, 0.10),
        ("turnover_20d", 80_000_000, 7, 0.20),
    ]
    pd.DataFrame(
        [
            {
                "symbol": "AAA.SH",
                "date": signal_date,
                "factor_name": factor_name,
                "factor_value": factor_value,
                "rank": rank,
                "percentile": percentile,
                "lookback_days": 60,
                "provider": "local",
                "updated_at": updated_at,
            }
            for factor_name, factor_value, rank, percentile in rows
        ]
    ).to_parquet(settings.clean_dir / "factors.parquet", index=False)
    pd.DataFrame(
        [{"symbol": "AAA.SH", "name": "沪深300ETF", "index_name": None}]
    ).to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)


def test_research_signal_score_and_risk_notes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_signal_fixture(tmp_path)

    signal = get_research_signal("AAA.SH")

    assert signal is not None
    assert signal.research_score == 64.5
    assert signal.priority == "观察优先级中"
    assert len(signal.components) == 6
    assert any("流动性待验证" in note for note in signal.explanation.risk_notes)
    assert any("波动风险偏高" in note for note in signal.explanation.risk_notes)
    assert any("回撤风险偏高" in note for note in signal.explanation.risk_notes)


def test_research_signals_api(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_signal_fixture(tmp_path)
    client = TestClient(app)

    list_response = client.get("/api/signals?limit=10")
    detail_response = client.get("/api/signals/AAA.SH")

    assert list_response.status_code == 200
    assert list_response.json()[0]["symbol"] == "AAA.SH"
    assert detail_response.status_code == 200
    assert detail_response.json()["research_score"] == 64.5


def test_signal_performance_route_is_not_captured_by_symbol_route(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    client = TestClient(app)

    response = client.get("/api/signals/performance?lookback_days=90&horizon_days=20")

    assert response.status_code == 200
    assert response.json() == []


def test_research_signals_filter_by_theme(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_signal_fixture(tmp_path)

    assert len(list_research_signals(theme="宽基指数")) == 1
    assert list_research_signals(theme="港股中概") == []


def test_research_signal_uses_dynamic_weights_when_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_signal_fixture(tmp_path)
    monkeypatch.setattr(
        "app.services.signal_service._signal_weights",
        lambda: (
            {"momentum_60d": 0.80, "volatility_30d": 0.20},
            "测试动态权重。",
        ),
    )

    signal = get_research_signal("AAA.SH")

    assert signal is not None
    assert signal.research_score == 82.0
    assert [component.factor_name for component in signal.components] == [
        "momentum_60d",
        "volatility_30d",
    ]
    assert any("测试动态权重" in note for note in signal.explanation.data_notes)
