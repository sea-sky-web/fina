"""为回测抓取一份独立的历史数据缓存 — 与实时信号路径完全分开。

用法：
    PYTHONPATH=backend python scripts/fetch_backtest_history.py

默认取当前"行业/主题ETF按成交额排名前 N"作为回测标的池，抓取每只ETF可获取的
全部历史日线，写入 data/backtest_cache/etf_daily.parquet + manifest.json。

注意（重要局限）：用"今天流动性最好的一批"去跑历史回测，隐含一点幸存者偏差——
这些ETF在历史早期未必都存在或都是当时最优选择。这是为了让 v1 回测足够简单能跑
起来做的简化，不是完整的时点还原(point-in-time)历史成分股重建。结论解读时要打
个折扣，不能当成"过去N年一直能这样选"的严格证明。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pandas as pd  # noqa: E402

from app import market_data  # noqa: E402
from app.signal_rule import CANDIDATE_POOL_SIZE, filter_universe  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "backtest_cache"
OUTPUT_PARQUET = OUTPUT_DIR / "etf_daily.parquet"
OUTPUT_MANIFEST = OUTPUT_DIR / "manifest.json"

BACKTEST_UNIVERSE_SIZE = 20
REQUEST_INTERVAL_SECONDS = 0.3


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".parquet.tmp", dir=str(path.parent))
    try:
        os.close(fd)
        frame.to_parquet(tmp, index=False)
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main() -> None:
    print("拉取全市场ETF现价快照...", file=sys.stderr)
    spot = market_data.fetch_etf_universe()
    universe = filter_universe(spot).head(BACKTEST_UNIVERSE_SIZE)
    symbols = universe["symbol"].tolist()
    names = dict(zip(universe["symbol"], universe["name"], strict=False))
    print(f"回测标的池：{len(symbols)} 只（今日行业/主题ETF成交额前{BACKTEST_UNIVERSE_SIZE}）", file=sys.stderr)

    frames: list[pd.DataFrame] = []
    rejected: dict[str, str] = {}
    for i, symbol in enumerate(symbols, start=1):
        try:
            daily = market_data.fetch_daily_bars(symbol, lookback_trading_days=100_000)
            frames.append(daily)
            print(f"  [{i}/{len(symbols)}] {symbol} {names.get(symbol, '')} {len(daily)} 行", file=sys.stderr)
        except Exception as exc:
            rejected[symbol] = str(exc)
            print(f"  [{i}/{len(symbols)}] {symbol} 拉取失败，跳过：{exc}", file=sys.stderr)
        time.sleep(REQUEST_INTERVAL_SECONDS)

    if not frames:
        raise SystemExit("没有任何标的抓取成功，无法生成回测数据缓存")

    combined = pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"])
    _write_parquet_atomic(combined, OUTPUT_PARQUET)

    manifest = {
        "fetched_at": date.today().isoformat(),
        "universe_size": len(symbols),
        "symbols": symbols,
        "names": names,
        "rejected": rejected,
        "rows": len(combined),
        "date_range": [str(combined["date"].min()), str(combined["date"].max())],
        "caveat": "使用当前流动性靠前的ETF做历史回测标的池，存在幸存者偏差，见脚本顶部说明。",
    }
    OUTPUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写入 {OUTPUT_PARQUET}（{len(combined)} 行）和 {OUTPUT_MANIFEST}", file=sys.stderr)


if __name__ == "__main__":
    main()
