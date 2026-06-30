from fastapi import APIRouter

from app.models import DataSourceAudit
from app.services.data_source_audit import audit_data_sources

router = APIRouter()


@router.get("/audit", response_model=DataSourceAudit)
def data_source_audit() -> DataSourceAudit:
    return audit_data_sources()
