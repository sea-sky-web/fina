from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.refresh_service import refresh_top_etfs
from app.services.rotation_service import build_rotation_report


@dataclass(frozen=True)
class DailySignalConfig:
    limit: int = 100
    lookback_days: int = 365
    top_n: int = 10


@dataclass(frozen=True)
class DailySignalReport:
    ok: bool
    generated_at: datetime
    refresh: dict[str, Any]
    radar_date: str | None
    rankings: list[dict[str, Any]]
    pools: dict[str, list[str]]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "generated_at": self.generated_at.isoformat(),
            "refresh": self.refresh,
            "radar_date": self.radar_date,
            "rankings": self.rankings,
            "pools": self.pools,
            "notes": self.notes,
        }


def build_daily_signal_report(config: DailySignalConfig) -> DailySignalReport:
    refresh_result = refresh_top_etfs(
        limit=config.limit,
        lookback_days=config.lookback_days,
        rebuild_factor_data=False,
    )
    rotation = build_rotation_report(top_n=config.top_n)
    rankings = [item.to_dict() for item in rotation.rankings]
    notes = [
        *rotation.data_notes,
        "评分权重: 景气30% / 动量25% / 估值15% / 结构10% / 流动性10% / 风险10%。",
        "本报告输出观察、配置和回避状态，不构成任何投资建议。",
    ]
    if refresh_result.failures:
        notes.append("刷新存在降级或失败标的，请查看 refresh.failures。")

    return DailySignalReport(
        ok=refresh_result.ok and bool(rankings),
        generated_at=datetime.now(UTC),
        refresh=refresh_result.model_dump(mode="json"),
        radar_date=rotation.date.isoformat() if rotation.date else None,
        rankings=rankings,
        pools={
            name: [item.symbol for item in scores]
            for name, scores in rotation.pools.items()
        },
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
        "",
        "## ETF 排名",
        "",
        "| 排名 | 代码 | 名称 | 类型 | 主题 | 总分 | 景气 | 动量 | 估值 | 风险 | 状态 | 动作 |",
        "| ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for index, item in enumerate(report.rankings, start=1):
        lines.append(
            "| "
            f"{index} | {item['symbol']} | {item['name']} | {item['etf_type']} | "
            f"{item['theme']} | {_format_score(item['total_score'])} | "
            f"{_format_score(item['boom_score'])} | {_format_score(item['momentum_score'])} | "
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
            f"景气: {item['boom_status']} {item['boom_score']:.1f}；"
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
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    args = parser.parse_args()

    report = build_daily_signal_report(
        DailySignalConfig(
            limit=args.limit,
            lookback_days=args.lookback_days,
            top_n=args.top_n,
        )
    )
    markdown = format_report_markdown(report)
    _write_text(args.output_md, markdown)
    _write_json(args.output_json, report.to_dict())
    print(markdown)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
