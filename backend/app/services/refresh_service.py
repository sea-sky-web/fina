from datetime import datetime

from app.jobs.collect_top_etfs import collect_top_etfs
from app.models import RefreshResult


def refresh_top_etfs(limit: int = 100, lookback_days: int = 365) -> RefreshResult:
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
    status = manifest.get("last_attempt_status")
    message = "刷新完成。"
    if status == "degraded":
        message = "刷新完成，但实时列表源不可用；已复用本地 ETF 列表并更新日线。"
    return RefreshResult(
        ok=True,
        message=message,
        provider=str(manifest.get("provider", "akshare")),
        selected_rows=int(manifest.get("selected_rows", 0)),
        daily_rows=int(manifest.get("daily_rows", 0)),
        refreshed_at=refreshed_at,
        failures=failures,
    )
