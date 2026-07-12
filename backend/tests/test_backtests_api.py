from datetime import UTC, date, datetime, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.backtest_service import run_research_signal_backtest
from app.synthesis import FALLBACK_SIGNAL_WEIGHTS


def _factor_rows(
    factor_dates: list[date],
    score_order_by_factor: dict[str, dict[str, float]],
) -> list[dict]:
    factor_rows = []
    updated_at = datetime(2026, 4, 10, tzinfo=UTC)
    for factor_date in factor_dates:
        for factor_name, score_order in score_order_by_factor.items():
            for rank, (symbol, percentile) in enumerate(score_order.items(), start=1):
                factor_rows.append(
                    {
                        "symbol": symbol,
                        "date": factor_date,
                        "factor_name": factor_name,
                        "factor_value": percentile,
                        "rank": rank,
                        "percentile": percentile,
                        "lookback_days": 60,
                        "provider": "local",
                        "updated_at": updated_at,
                    }
                )
    return factor_rows


def _write_backtest_fixture(
    processed_score_order_by_factor: dict[str, dict[str, float]] | None = None,
) -> None:
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    symbols = ["AAA.SH", "BBB.SH", "CCC.SH", "DDD.SH", "510300.SH"]
    start = date(2026, 1, 1)
    daily_rows = []
    for offset in range(100):
        current = start + timedelta(days=offset)
        daily_rows.extend(
            [
                {
                    "symbol": "AAA.SH",
                    "date": current,
                    "close": 100 + max(offset - 31, 0) * 0.9,
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "volume": 1000,
                    "amount": 1_000_000,
                    "factor": 1.0,
                    "provider": "test",
                },
                {
                    "symbol": "BBB.SH",
                    "date": current,
                    "close": 100 + max(offset - 31, 0) * 0.5,
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "volume": 1000,
                    "amount": 1_000_000,
                    "factor": 1.0,
                    "provider": "test",
                },
                {
                    "symbol": "CCC.SH",
                    "date": current,
                    "close": 100 - max(offset - 31, 0) * 0.1,
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "volume": 1000,
                    "amount": 1_000_000,
                    "factor": 1.0,
                    "provider": "test",
                },
                {
                    "symbol": "DDD.SH",
                    "date": current,
                    "close": 100 - max(offset - 31, 0) * 0.2,
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "volume": 1000,
                    "amount": 1_000_000,
                    "factor": 1.0,
                    "provider": "test",
                },
                {
                    "symbol": "510300.SH",
                    "date": current,
                    "close": 100 + max(offset - 31, 0) * 0.2,
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "volume": 1000,
                    "amount": 1_000_000,
                    "factor": 1.0,
                    "provider": "test",
                },
            ]
        )
    pd.DataFrame(daily_rows).to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)
    pd.DataFrame(
        [
            {"symbol": symbol, "name": f"{symbol}测试ETF", "index_name": None}
            for symbol in symbols
        ]
    ).to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)

    factor_dates = [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 5),
    ]
    score_order = {
        "AAA.SH": 1.00,
        "BBB.SH": 0.80,
        "CCC.SH": 0.40,
        "DDD.SH": 0.20,
        "510300.SH": 0.60,
    }
    factor_names = [*FALLBACK_SIGNAL_WEIGHTS, "turnover_20d"]
    raw_scores = {factor_name: score_order for factor_name in factor_names}
    processed_scores = processed_score_order_by_factor or raw_scores

    factor_rows = _factor_rows(factor_dates, raw_scores)
    processed_rows = _factor_rows(factor_dates, processed_scores)
    pd.DataFrame(factor_rows).to_parquet(settings.clean_dir / "factors.parquet", index=False)
    pd.DataFrame(processed_rows).to_parquet(
        settings.clean_dir / "factors_processed.parquet",
        index=False,
    )


def _write_rotation_core_fixture() -> None:
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range("2025-01-01", periods=180, freq="B").date
    configs = {
        "510300.SH": ("沪深300ETF", 1.00, 1.12, 300_000_000),
        "AAA.SH": ("半导体ETF", 1.00, 1.95, 600_000_000),
        "BBB.SH": ("芯片ETF", 1.00, 1.75, 500_000_000),
        "CCC.SH": ("医药ETF", 1.00, 1.02, 180_000_000),
        "DDD.SH": ("新能源ETF", 1.00, 0.86, 160_000_000),
    }
    daily_rows = []
    for symbol, (_, start, end, amount) in configs.items():
        closes = pd.Series(range(len(dates)), dtype="float64")
        closes = start + (end - start) * closes / max(len(dates) - 1, 1)
        for idx, current in enumerate(dates):
            daily_rows.append(
                {
                    "symbol": symbol,
                    "date": current,
                    "close": float(closes.iloc[idx]),
                    "open": float(closes.iloc[idx]),
                    "high": float(closes.iloc[idx]) * 1.01,
                    "low": float(closes.iloc[idx]) * 0.99,
                    "volume": 1000,
                    "amount": float(amount + idx * 100_000),
                    "factor": 1.0,
                    "provider": "test",
                }
            )
    pd.DataFrame(daily_rows).to_parquet(settings.clean_dir / "etf_daily.parquet", index=False)
    pd.DataFrame(
        [
            {"symbol": symbol, "name": name, "index_name": None}
            for symbol, (name, *_rest) in configs.items()
        ]
    ).to_parquet(settings.clean_dir / "etf_basic.parquet", index=False)


def test_research_signal_backtest_api_returns_portfolio_and_benchmarks(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_backtest_fixture()
    client = TestClient(app)

    response = client.get("/api/backtests/research-signal?top_n=2&cost_bps=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["top_n"] == 2
    assert payload["metrics"]["rebalance_count"] >= 2
    assert payload["equity_curve"]
    assert len(payload["benchmarks"]) == 2
    assert payload["holdings"][0]["rebalance_date"] == "2026-03-31"
    assert payload["holdings"][0]["effective_date"] == "2026-04-01"
    assert payload["equity_curve"][0]["date"] == "2026-04-01"
    assert payload["holdings"][0]["holdings"][0]["symbol"] == "AAA.SH"
    assert payload["validation"] is not None


def test_research_signal_backtest_cost_reduces_equity(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_backtest_fixture()

    no_cost = run_research_signal_backtest(top_n=2, cost_bps=0)
    with_cost = run_research_signal_backtest(top_n=2, cost_bps=20)

    assert no_cost.metrics.final_equity is not None
    assert with_cost.metrics.final_equity is not None
    assert with_cost.metrics.final_equity <= no_cost.metrics.final_equity


def test_research_signal_backtest_missing_benchmark_is_non_blocking(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_backtest_fixture()

    result = run_research_signal_backtest(top_n=2, benchmark="MISSING.SH")

    assert result.equity_curve
    assert len(result.benchmarks) == 1
    assert any("MISSING.SH" in note.message for note in result.data_notes)


def test_research_signal_backtest_uses_processed_factors(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    processed_score_order = {
        factor_name: {
            "BBB.SH": 1.00,
            "AAA.SH": 0.80,
            "510300.SH": 0.60,
            "CCC.SH": 0.40,
            "DDD.SH": 0.20,
        }
        for factor_name in [*FALLBACK_SIGNAL_WEIGHTS, "turnover_20d"]
    }
    _write_backtest_fixture(processed_score_order)

    result = run_research_signal_backtest(top_n=1, cost_bps=0)

    assert result.holdings
    assert result.holdings[0].holdings[0].symbol == "BBB.SH"


def test_research_signal_backtest_uses_dynamic_weights(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    processed_score_order = {
        factor_name: {
            "AAA.SH": 1.00,
            "BBB.SH": 0.80,
            "510300.SH": 0.60,
            "CCC.SH": 0.40,
            "DDD.SH": 0.20,
        }
        for factor_name in [*FALLBACK_SIGNAL_WEIGHTS, "turnover_20d"]
    }
    processed_score_order["volatility_30d"] = {
        "CCC.SH": 1.00,
        "AAA.SH": 0.80,
        "BBB.SH": 0.60,
        "510300.SH": 0.40,
        "DDD.SH": 0.20,
    }
    _write_backtest_fixture(processed_score_order)
    monkeypatch.setattr(
        "app.services.backtest_service._backtest_weights",
        lambda: ({"volatility_30d": 1.0}, "测试动态权重。"),
    )

    result = run_research_signal_backtest(top_n=1, cost_bps=0)

    assert result.holdings
    assert result.holdings[0].holdings[0].symbol == "CCC.SH"
    assert any("测试动态权重" in note.message for note in result.data_notes)


def test_research_signal_backtest_applies_risk_controls(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_backtest_fixture()

    result = run_research_signal_backtest(top_n=2, cost_bps=0)

    assert result.risk_summary is not None
    assert result.risk_summary.average_cash_weight is not None
    assert result.risk_summary.average_cash_weight > 0
    assert result.holdings[0].cash_weight > 0
    assert all(holding.weight <= 0.30 for holding in result.holdings[0].holdings)
    assert result.holdings[0].regime is not None


def test_rotation_core_backtest_api_returns_validated_research_pass(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_rotation_core_fixture()
    client = TestClient(app)

    response = client.get("/api/backtests/rotation-core?top_n=2&cost_bps=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["strategy"] == "rotation_core_risk_managed"
    assert payload["config"]["risk_managed"] is True
    assert payload["config"]["pool"] == "core_candidates"
    assert payload["config"]["min_risk_score"] == 60.0
    assert payload["metrics"]["rebalance_count"] >= 2
    assert payload["benchmarks"]
    assert payload["holdings"][0]["effective_date"] > payload["holdings"][0]["rebalance_date"]
    assert payload["risk_summary"]["average_cash_weight"] is not None
    assert payload["validation"]["status"] in {"research_pass", "production_pass"}
    assert payload["validation"]["excess_return_vs_benchmark"] > 0
    assert payload["validation"]["excess_return_vs_universe"] > 0
    assert any(
        item["key"] == "minimum_rebalances"
        for item in payload["validation"]["checks"]
    )
