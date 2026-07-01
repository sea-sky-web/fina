from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import PortfolioAdviceRequest, PortfolioHoldingInput
from app.services.data_source_audit import audit_data_sources
from app.services.portfolio_advice_service import build_portfolio_advice
from app.services.refresh_service import refresh_top_etfs
from app.services.rotation_service import build_rotation_report


@dataclass(frozen=True)
class DailySignalConfig:
    limit: int = 100
    lookback_days: int = 365
    top_n: int = 10
    holdings_file: str | None = None
    portfolio_target_count: int = 5
    min_trade_weight: float = 0.03


@dataclass(frozen=True)
class DailySignalReport:
    ok: bool
    generated_at: datetime
    refresh: dict[str, Any]
    data_source_audit: dict[str, Any]
    radar_date: str | None
    rankings: list[dict[str, Any]]
    pools: dict[str, list[str]]
    portfolio_advice: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "generated_at": self.generated_at.isoformat(),
            "refresh": self.refresh,
            "data_source_audit": self.data_source_audit,
            "radar_date": self.radar_date,
            "rankings": self.rankings,
            "pools": self.pools,
            "portfolio_advice": self.portfolio_advice,
            "notes": self.notes,
        }


def _load_holdings_file(path: str) -> list[PortfolioHoldingInput]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Holdings file not found: {source}")

    if source.suffix.lower() == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        rows = payload.get("holdings", []) if isinstance(payload, dict) else payload
    else:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

    holdings: list[PortfolioHoldingInput] = []
    for row in rows:
        if not row or not row.get("symbol"):
            continue
        holdings.append(
            PortfolioHoldingInput(
                symbol=str(row["symbol"]),
                weight=float(row["weight"]),
            )
        )
    return holdings


def build_daily_signal_report(config: DailySignalConfig) -> DailySignalReport:
    refresh_result = refresh_top_etfs(
        limit=config.limit,
        lookback_days=config.lookback_days,
        rebuild_factor_data=False,
    )
    data_audit = audit_data_sources()
    rotation = build_rotation_report(top_n=config.top_n)
    rankings = [item.to_dict() for item in rotation.rankings]
    notes = [
        *rotation.data_notes,
        "评分权重: 景气30% / 动量25% / 估值15% / 结构10% / 流动性10% / 风险10%。",
        "本报告输出观察、配置和回避状态，不构成任何投资建议。",
    ]
    portfolio_advice: dict[str, Any] | None = None
    if config.holdings_file:
        try:
            advice = build_portfolio_advice(
                PortfolioAdviceRequest(
                    holdings=_load_holdings_file(config.holdings_file),
                    target_count=config.portfolio_target_count,
                    universe_limit=min(max(config.limit, config.top_n), 200),
                    min_trade_weight=config.min_trade_weight,
                )
            )
            portfolio_advice = advice.model_dump(mode="json")
        except Exception as exc:
            notes.append(f"持仓调整研究建议生成失败: {exc}")
    if refresh_result.failures:
        notes.append("刷新存在降级或失败标的，请查看 refresh.failures。")
    for warning in data_audit.warnings:
        notes.append(f"数据源审计警告: {warning}")
    for error in data_audit.errors:
        notes.append(f"数据源审计错误: {error}")

    return DailySignalReport(
        ok=refresh_result.ok and data_audit.ok and bool(rankings),
        generated_at=datetime.now(UTC),
        refresh=refresh_result.model_dump(mode="json"),
        data_source_audit=data_audit.model_dump(mode="json"),
        radar_date=rotation.date.isoformat() if rotation.date else None,
        rankings=rankings,
        pools={
            name: [item.symbol for item in scores]
            for name, scores in rotation.pools.items()
        },
        portfolio_advice=portfolio_advice,
        notes=notes,
    )


def _format_percent(value: float | None) -> str:
    if value is None:
        return "无"
    return f"{value:.1%}"


def _format_score(value: float | None) -> str:
    if value is None:
        return "无"
    return f"{value:.1f}"


def _pool_name(name: str) -> str:
    return {
        "core_candidates": "可配置/重点跟踪",
        "watchlist": "观察池",
        "avoid": "回避/控仓池",
    }.get(name, name)


def format_report_markdown(report: DailySignalReport) -> str:
    refresh = report.refresh
    audit = report.data_source_audit
    lines = [
        "# 行业主题 ETF 轮动雷达",
        "",
        f"- 生成时间: {report.generated_at.isoformat()}",
        f"- 雷达日期: {report.radar_date or '无'}",
        f"- 刷新状态: {'OK' if refresh.get('ok') else 'FAILED'} - {refresh.get('message')}",
        (
            f"- 数据规模: ETF {refresh.get('selected_rows', 0)} / "
            f"日线 {refresh.get('daily_rows', 0)}"
        ),
        "- 轮动输入: clean ETF 日线 + config/etf_rotation_inputs.csv",
        f"- 数据源审计: {audit.get('status', 'unknown')}",
        "",
        "## 数据源真实性审计",
        "",
        f"- Provider: {audit.get('provider')}",
        f"- Manifest 状态: {audit.get('manifest_status')}",
        f"- 采集时间: {audit.get('collected_at') or '无'}",
        f"- 最新交易日: {audit.get('latest_trade_date') or '无'}",
        f"- 样本规模: ETF {audit.get('basic_rows', 0)} / 日线 {audit.get('daily_rows', 0)}",
        f"- 覆盖标的: {audit.get('symbols_with_daily', 0)} / {audit.get('symbols_total', 0)}",
        f"- Source endpoints: {', '.join(audit.get('source_endpoints') or []) or '无'}",
    ]
    warnings = audit.get("warnings") or []
    errors = audit.get("errors") or []
    if warnings:
        lines.append(f"- Warnings: {'；'.join(warnings)}")
    if errors:
        lines.append(f"- Errors: {'；'.join(errors)}")
    lines.extend(
        [
            "",
            "## ETF 排名",
            "",
            "| 排名 | 代码 | 名称 | 类型 | 主题 | 总分 | 景气 | 来源 | 动量 | "
            "估值 | 风险 | 状态 | 动作 |",
            "| ---: | --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for index, item in enumerate(report.rankings, start=1):
        lines.append(
            "| "
            f"{index} | {item['symbol']} | {item['name']} | {item['etf_type']} | "
            f"{item['theme']} | {_format_score(item['total_score'])} | "
            f"{_format_score(item['boom_score'])} | {item.get('boom_source', 'data')} | "
            f"{_format_score(item['momentum_score'])} | "
            f"{_format_score(item['valuation_score'])} | {_format_score(item['risk_score'])} | "
            f"{item['state']} | {item['action']} |"
        )

    lines.extend(["", "## 单 ETF 分析卡片", ""])
    for index, item in enumerate(report.rankings, start=1):
        returns = item.get("returns") or {}
        lines.append(
            f"{index}. {item['symbol']} {item['name']} - "
            f"{item['state']}，{item['action']}，总分 {item['total_score']:.1f}"
        )
        lines.append(
            f"   - 类型/主题: {item['etf_type']} / {item['theme']}；"
            f"景气: {item['boom_status']} {item['boom_score']:.1f}"
            f"（{item.get('boom_source', 'data')}）；"
            f"估值分位: {item['valuation_percentile']:.1f}%"
        )
        lines.append(
            f"   - 收益: 1月 {_format_percent(returns.get('1m'))}，"
            f"3月 {_format_percent(returns.get('3m'))}，"
            f"6月 {_format_percent(returns.get('6m'))}，"
            f"3月相对沪深300 {_format_percent(returns.get('relative_3m'))}"
        )
        lines.append(f"   - 优势: {'；'.join(item.get('drivers') or [])}")
        lines.append(f"   - 风险: {'；'.join(item.get('risk_notes') or [])}")
        if item.get("input_notes"):
            lines.append(f"   - 人工输入备注: {item['input_notes']}")

    lines.extend(["", "## 状态池", ""])
    for name, symbols in report.pools.items():
        lines.append(f"- {_pool_name(name)}: {', '.join(symbols) if symbols else '无'}")

    if report.portfolio_advice:
        advice = report.portfolio_advice
        regime = advice.get("market_regime") or {}
        lines.extend(
            [
                "",
                "## 持仓调整研究建议",
                "",
                f"- 当前暴露: {_format_percent(advice.get('current_exposure'))}",
                f"- 目标暴露: {_format_percent(advice.get('target_exposure'))}",
                f"- 现金/低风险权重: {_format_percent(advice.get('cash_weight'))}",
                f"- 估算换手: {_format_percent(advice.get('estimated_turnover'))}",
                f"- 市场状态: {regime.get('label_zh', '无')}",
                "",
                "| 动作 | 代码 | 名称 | 当前权重 | 目标权重 | 差值 | 状态 | 轮动动作 |",
                "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for item in advice.get("advice") or []:
            lines.append(
                "| "
                f"{item['action']} | {item['symbol']} | {item['name']} | "
                f"{_format_percent(item['current_weight'])} | "
                f"{_format_percent(item['target_weight'])} | "
                f"{_format_percent(item['delta_weight'])} | "
                f"{item['state']} | {item['rotation_action']} |"
            )
        lines.extend(["", "### 持仓建议依据", ""])
        for item in advice.get("advice") or []:
            rationale = "；".join(item.get("rationale") or [])
            lines.append(f"- {item['symbol']} {item['action']}: {rationale}")

    lines.extend(["", "## Notes", ""])
    for note in report.notes:
        lines.append(f"- {note}")
    failures = refresh.get("failures") or []
    if failures:
        lines.extend(["", "## Refresh Failures", ""])
        for failure in failures:
            lines.append(f"- {failure}")
    return "\n".join(lines) + "\n"


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
        description="Refresh ETF data and produce industry/theme rotation radar report."
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--holdings-file")
    parser.add_argument("--portfolio-target-count", type=int, default=5)
    parser.add_argument("--min-trade-weight", type=float, default=0.03)
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    args = parser.parse_args()

    report = build_daily_signal_report(
        DailySignalConfig(
            limit=args.limit,
            lookback_days=args.lookback_days,
            top_n=args.top_n,
            holdings_file=args.holdings_file,
            portfolio_target_count=args.portfolio_target_count,
            min_trade_weight=args.min_trade_weight,
        )
    )
    markdown = format_report_markdown(report)
    _write_text(args.output_md, markdown)
    _write_json(args.output_json, report.to_dict())
    print(markdown)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
