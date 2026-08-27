"""渲染买卖建议 markdown 报告。"""
from __future__ import annotations

from datetime import date

from app.benchmark import CashBenchmark
from app.portfolio_state import Decision

RISK_NOTE = (
    "本报告基于历史价格统计规则(20日动量排名 + 20日均线趋势确认)生成，不保证未来收益；"
    "止损16%是规则设定的离场阈值，不代表实际最大可能亏损。ETF存在市场、流动性和跟踪误差"
    "风险。本工具只输出研究性建议，所有买卖操作需要你自己在券商App手动确认和执行。"
)

_ACTION_ORDER = ("卖出", "买入", "持有")


def render_markdown(decisions: list[Decision], benchmark: CashBenchmark) -> str:
    today = date.today().isoformat()
    lines = [f"# ETF 实时信号报告 — {today}", ""]
    lines.append(
        f"**对照基准**：{benchmark.note}，当前七日年化约 {benchmark.annualized_pct:.2f}%"
        f"（样本 {benchmark.sample_size} 只，数据日期 {benchmark.as_of}）。"
    )
    lines.append("")

    for action in _ACTION_ORDER:
        group = [d for d in decisions if d.action == action]
        if not group:
            continue
        lines.append(f"## {action}")
        for d in group:
            price = f"，参考价 {d.price:.3f}" if d.price is not None else ""
            pnl = f"，浮动盈亏 {d.pnl_pct:.1%}" if d.pnl_pct is not None else ""
            lines.append(f"- **{d.name}**（{d.symbol}）{price}{pnl} — {d.reason}")
        lines.append("")

    if not decisions:
        lines.append("本次没有满足条件的候选标的，也没有持仓需要处理。")
        lines.append("")

    lines.append("## 风险提示")
    lines.append(RISK_NOTE)
    return "\n".join(lines)
