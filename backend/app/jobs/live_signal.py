"""实时信号计算入口。

用法：
    PYTHONPATH=backend python -m app.jobs.live_signal
    PYTHONPATH=backend python -m app.jobs.live_signal --output-md artifacts/live-signal.md

每次运行都现场向 AKShare 要数据，不读写任何行情缓存；只有 data/portfolio/live_state.json
记录你自己的持仓(symbol/买入价/买入日期)会被更新。
"""
from __future__ import annotations

import argparse
import sys
import time

from app import market_data
from app.benchmark import fetch_cash_benchmark
from app.portfolio_state import decide, load_state, save_state
from app.report import render_markdown
from app.signal_rule import compute_symbol_metrics, filter_universe, rank_candidates

REQUEST_INTERVAL_SECONDS = 0.3  # 限速，避免连续请求触发 AKShare 反爬


def run(output_path: str | None = None) -> str:
    print("拉取全市场ETF现价快照...", file=sys.stderr)
    spot = market_data.fetch_etf_universe()
    universe = filter_universe(spot)
    print(f"行业/主题ETF按成交额筛出候选 {len(universe)} 只，开始拉取日线...", file=sys.stderr)

    state = load_state()
    held_symbols = {h.symbol for h in state.holdings}
    name_lookup = dict(zip(universe["symbol"], universe["name"], strict=False))
    for holding in state.holdings:
        name_lookup.setdefault(holding.symbol, holding.name)

    symbols_to_fetch = list(dict.fromkeys([*universe["symbol"].tolist(), *held_symbols]))

    metrics_by_symbol = {}
    for i, symbol in enumerate(symbols_to_fetch, start=1):
        try:
            daily = market_data.fetch_daily_bars(symbol)
        except Exception as exc:
            print(f"  [{i}/{len(symbols_to_fetch)}] {symbol} 拉取失败，跳过：{exc}", file=sys.stderr)
            continue
        m = compute_symbol_metrics(symbol, name_lookup.get(symbol, symbol), daily)
        if m is not None:
            metrics_by_symbol[symbol] = m
        time.sleep(REQUEST_INTERVAL_SECONDS)

    ranked = rank_candidates(list(metrics_by_symbol.values()))
    print("查询货币基金对照基准...", file=sys.stderr)
    benchmark = fetch_cash_benchmark()

    decisions, new_state = decide(state, metrics_by_symbol, ranked)
    save_state(new_state)

    markdown = render_markdown(decisions, benchmark)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"报告已写入 {output_path}", file=sys.stderr)
    print(markdown)
    return markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="实时计算ETF动量+趋势信号，输出买卖建议")
    parser.add_argument("--output-md", default=None, help="markdown 报告输出路径")
    args = parser.parse_args()
    run(args.output_md)


if __name__ == "__main__":
    main()
