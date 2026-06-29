from datetime import datetime

from app.jobs.collect_top_etfs import collect_top_etfs
from app.models import RefreshResult
from app.services.factor_service import rebuild_factors


def refresh_top_etfs(
    limit: int = 100,
    lookback_days: int = 365,
    *,
    rebuild_factor_data: bool = True,
) -> RefreshResult:
    try:
        manifest = collect_top_etfs(limit=limit, lookback_days=lookback_days)
    except Exception as exc:  # noqa: BLE001
        return RefreshResult(
            ok=False,
            message="刷新失败，已保留上一次成功采集的数据。",
            failures=[{"stage": "refresh", "error": str(exc)}],
        )

    collected_at = manifest.get("collected_at")
    refreshed_at = datetime.fromisoformat(collected_at) if isinstance(collected_at, str) else None
    failures = list(manifest.get("failures", []))
    factor_rows = 0
    factor_latest_date = None
    if rebuild_factor_data:
        try:
            factor_result = rebuild_factors()
            factor_rows = int(factor_result.get("processed_rows", 0))
            latest_date = factor_result.get("latest_date")
            if isinstance(latest_date, str):
                factor_latest_date = datetime.fromisoformat(latest_date).date()
        except Exception as exc:  # noqa: BLE001
            failures.append({"stage": "factors", "error": str(exc)})
            return RefreshResult(
                ok=False,
                message="日线刷新完成，但因子重建失败；策略信号仍可能使用旧因子。",
                provider=str(manifest.get("provider", "akshare")),
                selected_rows=int(manifest.get("selected_rows", 0)),
                daily_rows=int(manifest.get("daily_rows", 0)),
                refreshed_at=refreshed_at,
                failures=failures,
            )

    status = manifest.get("last_attempt_status")
    message = "刷新完成，因子已重建。" if rebuild_factor_data else "刷新完成。"
    if status == "degraded":
        message = (
            "刷新完成但有降级；已尽量更新日线并重建因子。"
            if rebuild_factor_data
            else "刷新完成，但实时列表源不可用；已复用本地 ETF 列表并更新日线。"
        )
    return RefreshResult(
        ok=True,
        message=message,
        provider=str(manifest.get("provider", "akshare")),
        selected_rows=int(manifest.get("selected_rows", 0)),
        daily_rows=int(manifest.get("daily_rows", 0)),
        factor_rows=factor_rows,
        factor_latest_date=factor_latest_date,
        refreshed_at=refreshed_at,
        failures=failures,
    )
