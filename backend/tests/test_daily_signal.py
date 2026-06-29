from datetime import UTC, datetime

from app.jobs.daily_signal import (
    DailySignalReport,
    NotificationResult,
    _feishu_sign,
    format_report_markdown,
    notify_feishu,
)


def _report() -> DailySignalReport:
    return DailySignalReport(
        ok=True,
        generated_at=datetime(2026, 6, 30, 9, 30, tzinfo=UTC),
        refresh={
            "ok": True,
            "message": "刷新完成，因子已重建。",
            "selected_rows": 100,
            "daily_rows": 23000,
            "factor_rows": 145000,
            "factor_latest_date": "2026-06-30",
            "failures": [],
        },
        signal_date="2026-06-30",
        market_regime={
            "label_zh": "中性",
            "target_exposure": 0.75,
        },
        holdings=[
            {
                "symbol": "510300.SH",
                "name": "沪深300ETF",
                "theme": "宽基指数",
                "score": 88.5,
                "weight": 0.075,
                "risk_notes": [],
            }
        ],
        cash_weight=0.25,
        notes=["本报告仅用于研究观察，不构成任何投资建议。"],
    )


def test_format_report_markdown_contains_daily_signal_summary() -> None:
    markdown = format_report_markdown(_report())

    assert "Fina ETF Daily Signal" in markdown
    assert "2026-06-30" in markdown
    assert "510300.SH" in markdown
    assert "7.5%" in markdown


def test_notify_feishu_skips_without_webhook() -> None:
    result = notify_feishu("hello", webhook=None, secret=None)

    assert result == NotificationResult()


def test_feishu_sign_is_stable() -> None:
    assert _feishu_sign(1700000000, "secret") == "fiWS2+gh28DOydAv7hzONH/mDn9+b1Y4Y5ivXWXy8vA="
