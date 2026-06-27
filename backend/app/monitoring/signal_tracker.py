from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pandas as pd

from app.core.config import settings
from app.storage.parquet_store import read_parquet, write_parquet


@dataclass
class SignalPerformance:
    snapshot_date: date
    horizon_days: int
    top_mean_return: float = 0.0
    benchmark_return: float = 0.0
    excess_return: float = 0.0
    hit_rate: float = 0.0
    score_return_corr: float | None = None
    top_symbols: list[str] = field(default_factory=list)
    data_notes: list[str] = field(default_factory=list)


def _snapshot_path() -> str:
    return "signal_snapshots"


def take_signal_snapshot(
    signal_date: date,
    signals: list[dict],
    top_n: int = 20,
) -> dict:
    """Persist the current top-N signal list for later performance review."""
    if not signals:
        return {"ok": False, "message": "无信号数据，跳过快照。"}

    rows = []
    for rank, signal in enumerate(signals[:top_n], start=1):
        rows.append(
            {
                "snapshot_date": signal_date,
                "rank": rank,
                "symbol": signal.get("symbol", ""),
                "name": signal.get("name", ""),
                "theme": signal.get("theme", ""),
                "research_score": signal.get("research_score", 0.0),
                "recorded_at": datetime.now(UTC),
            }
        )

    frame = pd.DataFrame(rows)
    snapshots = read_parquet(settings.clean_dir / f"{_snapshot_path()}.parquet")
    if not snapshots.empty:
        snapshots = snapshots[snapshots["snapshot_date"] != pd.Timestamp(signal_date)]
        frame = pd.concat([snapshots, frame], ignore_index=True)
    write_parquet(frame, settings.clean_dir / f"{_snapshot_path()}.parquet")
    return {
        "ok": True,
        "date": signal_date.isoformat(),
        "rows": int(len(frame)),
    }


def evaluate_past_signal(
    snapshot_date: date,
    horizon_days: int = 20,
    benchmark: str = "510300.SH",
) -> SignalPerformance | None:
    """Look back at a past signal snapshot and measure actual forward performance."""
    snapshots = read_parquet(settings.clean_dir / f"{_snapshot_path()}.parquet")
    if snapshots.empty:
        return None

    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"]).dt.date
    day_rows = snapshots[snapshots["snapshot_date"] == snapshot_date]
    if day_rows.empty:
        return None

    daily = read_parquet(settings.clean_dir / "etf_daily.parquet")
    if daily.empty or not {"symbol", "date", "close"}.issubset(daily.columns):
        return None

    daily = daily[["symbol", "date", "close"]].copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = daily.dropna(subset=["symbol", "date", "close"]).sort_values(["symbol", "date"])

    forward_start = snapshot_date
    forward_end_candidates = sorted(
        value for value in daily["date"].unique() if value > forward_start
    )
    if len(forward_end_candidates) < horizon_days:
        return None
    forward_end = forward_end_candidates[min(horizon_days - 1, len(forward_end_candidates) - 1)]

    forward_data = daily[
        (daily["date"] >= forward_start) & (daily["date"] <= forward_end)
    ]
    if forward_data.empty:
        return None

    start_prices = forward_data[forward_data["date"] == forward_data["date"].min()]
    end_prices = forward_data[forward_data["date"] == forward_data["date"].max()]
    returns = {}
    for symbol in day_rows["symbol"].tolist():
        start_row = start_prices[start_prices["symbol"] == symbol]
        end_row = end_prices[end_prices["symbol"] == symbol]
        if start_row.empty or end_row.empty:
            continue
        ret = float(end_row["close"].iloc[0] / start_row["close"].iloc[0] - 1)
        returns[symbol] = ret

    if not returns:
        return None

    top_returns = [returns[sym] for sym in day_rows["symbol"] if sym in returns]
    if not top_returns:
        return None

    top_mean = float(pd.Series(top_returns).mean())

    benchmark_ret = 0.0
    bench_start = start_prices[start_prices["symbol"] == benchmark]
    bench_end = end_prices[end_prices["symbol"] == benchmark]
    if not bench_start.empty and not bench_end.empty:
        benchmark_ret = float(bench_end["close"].iloc[0] / bench_start["close"].iloc[0] - 1)

    hit_count = sum(1 for ret in top_returns if ret > benchmark_ret)
    hit_rate = hit_count / len(top_returns) if top_returns else 0.0

    scores = day_rows.set_index("symbol")["research_score"].to_dict()
    score_ret_pairs = [
        (scores.get(sym, 0.0), returns[sym])
        for sym in returns
        if sym in scores
    ]
    score_return_corr = None
    if len(score_ret_pairs) > 3:
        s = pd.Series([p[0] for p in score_ret_pairs])
        r = pd.Series([p[1] for p in score_ret_pairs])
        if s.std() > 0 and r.std() > 0:
            score_return_corr = float(s.corr(r))

    return SignalPerformance(
        snapshot_date=snapshot_date,
        horizon_days=horizon_days,
        top_mean_return=top_mean,
        benchmark_return=benchmark_ret,
        excess_return=top_mean - benchmark_ret,
        hit_rate=hit_rate,
        score_return_corr=score_return_corr,
        top_symbols=list(returns.keys()),
        data_notes=[
            f"快照日期 {snapshot_date.isoformat()} 的 Top-{len(top_returns)} 信号回顾。",
            f"前瞻 {horizon_days} 个交易日（至 {forward_end.isoformat()}）。",
            "本回顾仅用于信号质量研究，不构成投资建议。",
        ],
    )


def recent_signal_performance(
    lookback_days: int = 90,
    horizon_days: int = 20,
) -> list[SignalPerformance]:
    """Review all snapshots taken in the recent past."""
    snapshots = read_parquet(settings.clean_dir / f"{_snapshot_path()}.parquet")
    if snapshots.empty:
        return []

    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"]).dt.date
    cutoff = date.today()
    earliest = min(snapshots["snapshot_date"].max(), cutoff)
    start_date = earliest - pd.Timedelta(days=lookback_days)
    if hasattr(start_date, "date"):
        start_date = start_date.date()

    recent_dates = sorted(
        value
        for value in snapshots["snapshot_date"].unique()
        if value >= start_date
    )
    results = []
    for snapshot_date in recent_dates:
        perf = evaluate_past_signal(snapshot_date, horizon_days=horizon_days)
        if perf is not None:
            results.append(perf)
    return results
