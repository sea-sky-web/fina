from __future__ import annotations

from datetime import date

import pandas as pd

from app.core.config import settings
from app.services.rotation_service import build_rotation_report, infer_etf_type


def _write_rotation_fixture(tmp_path) -> None:
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range("2025-12-01", periods=150, freq="B").date
    rows = []
    configs = {
        "510300.SH": ("沪深300ETF", 1.00, 1.12, 300_000_000),
        "AAA.SH": ("半导体ETF", 1.00, 1.55, 500_000_000),
        "BBB.SH": ("医药ETF", 1.00, 0.95, 50_000_000),
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


def _manual_inputs(tmp_path) -> str:
    path = tmp_path / "rotation_inputs.csv"
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
    ).to_csv(path, index=False)
    return str(path)


def test_infer_etf_type_for_industry_and_cash() -> None:
    assert infer_etf_type("半导体ETF", "半导体芯片") == "行业"
    assert infer_etf_type("货币ETF", "货币现金") == "货币债券"


def test_build_rotation_report_scores_industry_theme_etfs(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_rotation_fixture(tmp_path)
    input_path = _manual_inputs(tmp_path)

    report = build_rotation_report(top_n=3, input_path=input_path)

    assert report.date == date(2026, 6, 26)
    assert report.rankings[0].symbol == "AAA.SH"
    assert report.rankings[0].action == "主线候选"
    assert report.rankings[0].boom_score >= 70
    assert report.rankings[0].boom_status == "上行"
    assert report.rankings[0].boom_source == "data+manual"
    assert {item.etf_type for item in report.rankings} == {"行业"}
    assert "510300.SH" not in [item.symbol for item in report.rankings]
    assert "AAA.SH" in [item.symbol for item in report.pools["core_candidates"]]
    assert any("仅比较行业和主题 ETF" in note for note in report.data_notes)
    assert any("人工输入文件" in note for note in report.data_notes)
