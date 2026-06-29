from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import settings
from app.risk import build_risk_adjusted_portfolio, detect_market_regime
from app.services.refresh_service import refresh_top_etfs
from app.services.signal_service import list_research_signals
from app.storage.parquet_store import read_parquet


@dataclass(frozen=True)
class DailySignalConfig:
    limit: int = 100
    lookback_days: int = 365
    top_n: int = 10


@dataclass(frozen=True)
class NotificationResult:
    status: str = "skipped"
    message: str = "Feishu webhook is not configured."


@dataclass(frozen=True)
class DailySignalReport:
    ok: bool
    generated_at: datetime
    refresh: dict[str, Any]
    signal_date: str | None
    market_regime: dict[str, Any]
    holdings: list[dict[str, Any]]
    cash_weight: float | None = None
    notes: list[str] = field(default_factory=list)
    notification: NotificationResult = field(default_factory=NotificationResult)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "generated_at": self.generated_at.isoformat(),
            "refresh": self.refresh,
            "signal_date": self.signal_date,
            "market_regime": self.market_regime,
            "holdings": self.holdings,
            "cash_weight": self.cash_weight,
            "notes": self.notes,
            "notification": {
                "status": self.notification.status,
                "message": self.notification.message,
            },
        }


def _daily_for_regime() -> pd.DataFrame:
    daily = read_parquet(settings.clean_dir / "etf_daily.parquet")
    if daily.empty:
        return pd.DataFrame(columns=["symbol", "date", "close"])
    keep = [column for column in ["symbol", "date", "close"] if column in daily.columns]
    return daily[keep].copy()


def _portfolio_from_signals(
    signals,
    signal_date,
) -> tuple[list[dict[str, Any]], float | None, list[str]]:
    if not signals or signal_date is None:
        return [], None, ["没有可用研究信号。"]

    daily = _daily_for_regime()
    regime = detect_market_regime(daily, signal_date)
    top_signals = signals
    portfolio = build_risk_adjusted_portfolio(
        symbols=[signal.symbol for signal in top_signals],
        scores={signal.symbol: signal.research_score for signal in top_signals},
        daily=daily,
        as_of=signal_date,
        themes={signal.symbol: signal.theme for signal in top_signals},
        regime=regime,
    )
    rows = []
    for signal in top_signals:
        rows.append(
            {
                "symbol": signal.symbol,
                "name": signal.name,
                "theme": signal.theme,
                "score": signal.research_score,
                "weight": portfolio.weights.get(signal.symbol, 0.0),
                "risk_notes": signal.explanation.risk_notes,
            }
        )
    return rows, portfolio.cash_weight, portfolio.notes


def build_daily_signal_report(config: DailySignalConfig) -> DailySignalReport:
    refresh_result = refresh_top_etfs(
        limit=config.limit,
        lookback_days=config.lookback_days,
        rebuild_factor_data=True,
    )
    signals = list_research_signals(limit=config.top_n)
    signal_date = signals[0].date if signals else None
    daily = _daily_for_regime()
    regime = detect_market_regime(daily, signal_date)
    holdings, cash_weight, portfolio_notes = _portfolio_from_signals(signals, signal_date)
    notes = [*portfolio_notes, "本报告仅用于研究观察，不构成任何投资建议。"]
    if refresh_result.failures:
        notes.append("刷新存在降级或失败标的，请查看 refresh.failures。")

    return DailySignalReport(
        ok=refresh_result.ok and bool(holdings),
        generated_at=datetime.now(UTC),
        refresh=refresh_result.model_dump(mode="json"),
        signal_date=signal_date.isoformat() if signal_date else None,
        market_regime={
            "label": regime.label,
            "label_zh": regime.label_zh,
            "date": regime.date.isoformat() if regime.date else None,
            "target_exposure": regime.target_exposure,
            "trend_score": regime.trend_score,
            "volatility_annualized": regime.volatility_annualized,
            "drawdown": regime.drawdown,
            "source": regime.source,
            "data_notes": regime.data_notes,
        },
        holdings=holdings,
        cash_weight=cash_weight,
        notes=notes,
    )


def format_report_markdown(report: DailySignalReport) -> str:
    refresh = report.refresh
    lines = [
        "# Fina ETF Daily Signal",
        "",
        f"- 生成时间: {report.generated_at.isoformat()}",
        f"- 信号日期: {report.signal_date or '无'}",
        f"- 刷新状态: {'OK' if refresh.get('ok') else 'FAILED'} - {refresh.get('message')}",
        (
            f"- 数据规模: ETF {refresh.get('selected_rows', 0)} / "
            f"日线 {refresh.get('daily_rows', 0)} / "
            f"因子 {refresh.get('factor_rows', 0)}"
        ),
        f"- 因子最新日期: {refresh.get('factor_latest_date') or '无'}",
        (
            f"- 市场状态: {report.market_regime.get('label_zh')} / "
            f"目标暴露 {report.market_regime.get('target_exposure', 0):.0%}"
        ),
        f"- 现金或低风险仓位: {(report.cash_weight or 0):.0%}",
        "",
        "## Top Holdings",
        "",
        "| 权重 | 代码 | 名称 | 主题 | 研究分 |",
        "| ---: | --- | --- | --- | ---: |",
    ]
    for item in report.holdings:
        lines.append(
            "| "
            f"{item['weight']:.1%} | {item['symbol']} | {item['name']} | "
            f"{item['theme']} | {item['score']:.2f} |"
        )
    lines.extend(["", "## Notes", ""])
    for note in report.notes:
        lines.append(f"- {note}")
    failures = refresh.get("failures") or []
    if failures:
        lines.extend(["", "## Refresh Failures", ""])
        for failure in failures:
            lines.append(f"- {failure}")
    return "\n".join(lines) + "\n"


def _feishu_sign(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def notify_feishu(text: str, webhook: str | None, secret: str | None = None) -> NotificationResult:
    if not webhook:
        return NotificationResult()

    payload: dict[str, Any] = {
        "msg_type": "text",
        "content": {"text": text},
    }
    if secret:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = _feishu_sign(timestamp, secret)

    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        return NotificationResult(status="failed", message=str(exc))

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return NotificationResult(status="failed", message=f"Unexpected Feishu response: {body}")
    if parsed.get("code") not in {0, None}:
        return NotificationResult(status="failed", message=str(parsed))
    return NotificationResult(status="sent", message="Feishu notification sent.")


def _write_text(path: str | None, text: str) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _write_json(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh ETF data and produce daily signal report."
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--notify-feishu", action="store_true")
    args = parser.parse_args()

    report = build_daily_signal_report(
        DailySignalConfig(
            limit=args.limit,
            lookback_days=args.lookback_days,
            top_n=args.top_n,
        )
    )
    markdown = format_report_markdown(report)
    notification = NotificationResult()
    if args.notify_feishu:
        notification = notify_feishu(
            markdown,
            webhook=os.environ.get("FEISHU_BOT_WEBHOOK"),
            secret=os.environ.get("FEISHU_BOT_SECRET"),
        )
        report = DailySignalReport(
            ok=report.ok,
            generated_at=report.generated_at,
            refresh=report.refresh,
            signal_date=report.signal_date,
            market_regime=report.market_regime,
            holdings=report.holdings,
            cash_weight=report.cash_weight,
            notes=report.notes,
            notification=notification,
        )

    _write_text(args.output_md, markdown)
    _write_json(args.output_json, report.to_dict())
    print(markdown)
    print(f"Notification: {notification.status} - {notification.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
