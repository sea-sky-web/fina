from fastapi import APIRouter

from app.models import MonitoringReport
from app.monitoring.health import build_monitoring_report

router = APIRouter()


@router.get("/report", response_model=MonitoringReport)
def monitoring_report() -> MonitoringReport:
    return build_monitoring_report()
