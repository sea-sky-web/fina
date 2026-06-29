from datetime import UTC, datetime

from app.jobs.daily_signal import (
    DailySignalReport,
    NotificationResult,
    _feishu_sign,
    format_report_markdown,
    main,
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
            "label": "neutral",
            "label_zh": "中性",
            "target_exposure": 0.75,
            "source": "510300.SH",
            "trend_score": 0.01,
            "volatility_annualized": 0.2,
            "drawdown": -0.03,
            "data_notes": ["市场状态参考 510300.SH。"],
        },
        holdings=[
            {
                "symbol": "510300.SH",
                "name": "沪深300ETF",
                "theme": "宽基指数",
                "score": 88.5,
                "weight": 0.075,
                "risk_notes": ["短期波动风险偏高。"],
                "components": [
                    {
                        "factor_name": "turnover_20d",
                        "label": "20日均成交额",
                        "percentile": 0.9,
                        "rank": 1,
                        "contribution": 90.0,
                    }
                ],
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
    assert "Market Regime" in markdown
    assert "Holding Details" in markdown
    assert "20日均成交额" in markdown
    assert "短期波动风险偏高" in markdown


def test_notify_feishu_skips_without_webhook() -> None:
    result = notify_feishu("hello", webhook=None, secret=None)

    assert result == NotificationResult()


def test_feishu_sign_is_stable() -> None:
    assert _feishu_sign(1700000000, "secret") == "fiWS2+gh28DOydAv7hzONH/mDn9+b1Y4Y5ivXWXy8vA="


def test_require_notification_fails_when_feishu_is_not_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("FEISHU_BOT_WEBHOOK", raising=False)
    monkeypatch.delenv("FEISHU_BOT_SECRET", raising=False)
    monkeypatch.setattr("app.jobs.daily_signal.build_daily_signal_report", lambda config: _report())
    monkeypatch.setattr(
        "sys.argv",
        [
            "daily_signal",
            "--output-md",
            str(tmp_path / "report.md"),
            "--notify-feishu",
            "--require-notification",
        ],
    )

    assert main() == 1
