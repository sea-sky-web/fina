from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from app.core.config import settings
from app.models import MarketRegimeSnapshot, MonitoringCheck, MonitoringReport
from app.monitoring.signal_tracker import recent_signal_performance
from app.risk import MarketRegime, detect_market_regime
from app.services.evaluation_service import generate_factor_pool_report
from app.services.status_service import get_data_status
from app.storage.parquet_store import read_parquet


def _check(key: str, label: str, status: str, value: str, detail: str) -> MonitoringCheck:
    return MonitoringCheck(key=key, label=label, status=status, value=value, detail=detail)


def _regime_snapshot(regime: MarketRegime) -> MarketRegimeSnapshot:
    return MarketRegimeSnapshot(
        label=regime.label,
        label_zh=regime.label_zh,
        date=regime.date,
        target_exposure=regime.target_exposure,
        trend_score=regime.trend_score,
        volatility_annualized=regime.volatility_annualized,
        drawdown=regime.drawdown,
        source=regime.source,
        data_notes=regime.data_notes,
    )


def _data_check() -> MonitoringCheck:
    statuses = get_data_status()
    if not statuses:
        return _check("data", "数据状态", "missing", "无状态", "未读取到任何清洗数据状态。")
    bad = [item for item in statuses if item.status in {"empty", "error"}]
    stale = [item for item in statuses if item.status == "stale"]
    rows = sum(item.rows for item in statuses)
    latest = max((item.last_trade_date for item in statuses if item.last_trade_date), default=None)
    if bad:
        return _check("data", "数据状态", "alert", f"{len(bad)} 异常", bad[0].message)
    if stale:
        return _check("data", "数据状态", "watch", f"{len(stale)} 过期", stale[0].message)
    return _check("data", "数据状态", "ok", f"{rows:,} rows", f"最新交易日 {latest or '-'}。")


def _factor_check() -> MonitoringCheck:
    try:
        report = generate_factor_pool_report(horizons=[20], processed=True)
    except Exception as exc:
        return _check("factor_pool", "因子池", "alert", "评估失败", str(exc))

    if report.pool_health == "健康":
        return _check(
            "factor_pool",
            "因子池",
            "ok",
            f"{len(report.individual_reports)} factors",
            "因子池暂未发现高冗余结构。",
        )
    status = "watch" if report.pool_health == "冗余" else "alert"
    detail = report.recommendations[0] if report.recommendations else "因子池需要继续观察。"
    return _check("factor_pool", "因子池", status, report.pool_health, detail)


def _snapshot_check() -> MonitoringCheck:
    snapshots = read_parquet(settings.clean_dir / "signal_snapshots.parquet")
    if snapshots.empty:
        return _check("signal_snapshot", "信号快照", "missing", "0", "尚未保存信号快照。")
    snapshots = snapshots.copy()
    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"]).dt.date
    latest = snapshots["snapshot_date"].max()
    count = snapshots["snapshot_date"].nunique()
    return _check("signal_snapshot", "信号快照", "ok", f"{count} days", f"最近快照 {latest}。")


def _performance_check() -> MonitoringCheck:
    results = recent_signal_performance(lookback_days=180, horizon_days=20)
    if not results:
        return _check(
            "signal_performance",
            "信号复盘",
            "watch",
            "样本不足",
            "暂无可评价的成熟快照。",
        )
    avg_excess = float(pd.Series([item.excess_return for item in results]).mean())
    avg_hit = float(pd.Series([item.hit_rate for item in results]).mean())
    if avg_excess < -0.02:
        status = "alert"
    elif avg_excess <= 0 or avg_hit < 0.5:
        status = "watch"
    else:
        status = "ok"
    return _check(
        "signal_performance",
        "信号复盘",
        status,
        f"{avg_excess:.2%} excess",
        f"近 {len(results)} 个成熟快照平均胜率 {avg_hit:.0%}。",
    )


def _regime_check(regime: MarketRegime) -> MonitoringCheck:
    status = "watch" if regime.label == "risk_off" else "ok"
    return _check(
        "market_regime",
        "市场状态",
        status,
        regime.label_zh,
        f"目标风险暴露 {regime.target_exposure:.0%}。",
    )


def build_monitoring_report() -> MonitoringReport:
    daily = read_parquet(settings.clean_dir / "etf_daily.parquet")
    regime = detect_market_regime(daily)
    checks = [
        _data_check(),
        _factor_check(),
        _snapshot_check(),
        _performance_check(),
        _regime_check(regime),
    ]
    alerts = [
        f"{item.label}: {item.detail}"
        for item in checks
        if item.status in {"alert", "watch", "missing"}
    ]
    return MonitoringReport(
        generated_at=datetime.now(UTC),
        market_regime=_regime_snapshot(regime),
        checks=checks,
        alerts=alerts,
        data_notes=[
            "监控报告只读取现有清洗数据、因子评估缓存和信号快照，不触发数据采集或下单。",
            "后端 API 或自动化任务可以读取该报告作为持续监控视图。",
        ],
    )
