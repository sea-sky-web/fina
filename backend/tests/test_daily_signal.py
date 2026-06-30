from datetime import UTC, datetime

from app.jobs.daily_signal import DailySignalReport, format_report_markdown, main


def _report() -> DailySignalReport:
    return DailySignalReport(
        ok=True,
        generated_at=datetime(2026, 6, 30, 9, 30, tzinfo=UTC),
        refresh={
            "ok": True,
            "message": "刷新完成。",
            "selected_rows": 100,
            "daily_rows": 23000,
            "failures": [],
        },
        data_source_audit={
            "ok": True,
            "status": "ok",
            "provider": "akshare",
            "manifest_status": "ok",
            "collected_at": "2026-06-30T09:20:00+00:00",
            "latest_trade_date": "2026-06-30",
            "basic_rows": 100,
            "daily_rows": 23000,
            "symbols_total": 100,
            "symbols_with_daily": 100,
            "source_endpoints": ["fund_etf_spot_em", "fund_etf_hist_sina"],
            "warnings": [],
            "errors": [],
        },
        radar_date="2026-06-30",
        rankings=[
            {
                "symbol": "510300.SH",
                "name": "沪深300ETF",
                "theme": "宽基指数",
                "etf_type": "宽基",
                "total_score": 78.5,
                "boom_score": 70.0,
                "momentum_score": 82.0,
                "valuation_score": 55.0,
                "risk_score": 68.0,
                "boom_status": "上行",
                "boom_source": "data",
                "valuation_percentile": 45.0,
                "state": "景气上行 + 动量确认",
                "action": "主线候选",
                "returns": {"1m": 0.03, "3m": 0.12, "6m": 0.18, "relative_3m": 0.04},
                "drivers": ["景气评分较高", "相对动量较强"],
                "risk_notes": ["未触发核心风险阈值。"],
                "input_notes": "人工景气输入",
            }
        ],
        pools={
            "core_candidates": ["510300.SH"],
            "watchlist": [],
            "avoid": [],
        },
        notes=["本报告输出观察、配置和回避状态，不构成任何投资建议。"],
    )


def test_format_report_markdown_contains_rotation_radar_sections() -> None:
    markdown = format_report_markdown(_report())

    assert "行业主题 ETF 轮动雷达" in markdown
    assert "ETF 排名" in markdown
    assert "数据源真实性审计" in markdown
    assert "单 ETF 分析卡片" in markdown
    assert "状态池" in markdown
    assert "510300.SH" in markdown
    assert "景气上行 + 动量确认" in markdown
    assert "| 1 | 510300.SH | 沪深300ETF | 宽基 | 宽基指数 | 78.5 | 70.0 | data |" in markdown
    assert "3月相对沪深300 4.0%" in markdown


def test_main_writes_report_outputs(monkeypatch, tmp_path) -> None:
    output_md = tmp_path / "daily.md"
    output_json = tmp_path / "daily.json"
    monkeypatch.setattr("app.jobs.daily_signal.build_daily_signal_report", lambda config: _report())
    monkeypatch.setattr(
        "sys.argv",
        [
            "daily_signal",
            "--output-md",
            str(output_md),
            "--output-json",
            str(output_json),
        ],
    )

    assert main() == 0
    assert "行业主题 ETF 轮动雷达" in output_md.read_text()
    assert '"data_source_audit"' in output_json.read_text()
    assert '"radar_date": "2026-06-30"' in output_json.read_text()
