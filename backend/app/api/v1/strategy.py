from __future__ import annotations

import csv
import json
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.core.config import PROJECT_ROOT
from app.models import StrategyParams, StrategySignalReport
from app.services.strategy_config import load_strategy_params
from app.services.strategy_signal_service import generate_strategy_signal
from app.services.strategy_state import reset_state

router = APIRouter()

_ARTIFACTS = PROJECT_ROOT / "artifacts"


@router.get("/signal", response_model=StrategySignalReport)
def strategy_signal(
    signal_date: Annotated[date | None, Query(alias="date")] = None,
) -> StrategySignalReport:
    """Generate sector rotation signal for the given date."""
    return generate_strategy_signal(signal_date=signal_date)


@router.get("/config", response_model=StrategyParams)
def strategy_config() -> StrategyParams:
    """Return current strategy configuration (version + params)."""
    return load_strategy_params()


@router.post("/reset-state")
def strategy_reset() -> dict[str, str]:
    """Reset strategy portfolio state (entry prices, cooldowns, holdings)."""
    reset_state()
    return {"status": "ok", "message": "strategy portfolio state reset"}


@router.get("/backtest/{version}")
def strategy_backtest(version: str) -> dict[str, Any]:
    """Return walk-forward backtest results for a strategy version."""
    version = version.lower().removeprefix("v")
    report_path = _ARTIFACTS / f"backtest_v{version}" / "report.json"
    windows_path = _ARTIFACTS / f"backtest_v{version}" / "windows.csv"

    if not report_path.exists():
        return {"error": f"backtest_v{version} not found"}

    report = json.loads(report_path.read_text(encoding="utf-8"))

    windows: list[dict[str, Any]] = []
    if windows_path.exists():
        with open(windows_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for k in ["window_return", "bench_window_return", "excess_vs_bench",
                           "window_max_drawdown", "window_sharpe", "train_objective"]:
                    if k in row:
                        row[k] = float(row[k])
                if "window" in row:
                    row["window"] = int(row["window"])
                if "best_K" in row:
                    row["best_K"] = int(row["best_K"])
                if "beat_bench" in row:
                    row["beat_bench"] = row["beat_bench"] == "True"
                windows.append(row)

    equity: list[dict[str, Any]] = []
    cum = 1.0
    bench_cum = 1.0
    for w in windows:
        cum *= (1 + w.get("window_return", 0))
        bench_cum *= (1 + w.get("bench_window_return", 0))
        equity.append({
            "date": w.get("test_end", ""),
            "equity": round(cum, 4),
            "benchmark": round(bench_cum, 4),
            "window_return": w.get("window_return", 0),
        })

    return {
        "version": f"V{version}",
        "summary": {k: report[k] for k in [
            "annualized_return", "sharpe", "max_drawdown", "win_rate",
            "max_consecutive_losing_windows", "worst_window",
            "cost_decay_rate", "param_cv_K",
        ] if k in report},
        "checklist": report.get("checklist", {}),
        "equity_curve": equity,
        "windows": windows,
    }


@router.get("/versions")
def strategy_versions() -> list[dict[str, Any]]:
    """List all available backtest versions with key metrics."""
    versions = []
    if not _ARTIFACTS.exists():
        return versions
    for d in sorted(_ARTIFACTS.iterdir()):
        if not d.is_dir() or not d.name.startswith("backtest_v"):
            continue
        report_path = d / "report.json"
        if not report_path.exists():
            continue
        try:
            r = json.loads(report_path.read_text(encoding="utf-8"))
            passes = sum(1 for v in r.get("checklist", {}).values() if v is True)
            versions.append({
                "version": d.name.replace("backtest_", "").upper(),
                "annual_return": r.get("annualized_return"),
                "sharpe": r.get("sharpe"),
                "max_drawdown": r.get("max_drawdown"),
                "win_rate": r.get("win_rate"),
                "pass_count": passes,
            })
        except Exception:
            continue
    return versions
