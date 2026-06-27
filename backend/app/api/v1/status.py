from fastapi import APIRouter

from app.models import DataStatus
from app.services.status_service import get_data_status

router = APIRouter()


@router.get("/status", response_model=list[DataStatus])
def status() -> list[DataStatus]:
    return get_data_status()
