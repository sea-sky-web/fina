from fastapi import APIRouter, Query

from app.models import RotationReportModel, RotationScoreModel
from app.services.rotation_service import build_rotation_report

router = APIRouter()


@router.get("/report", response_model=RotationReportModel)
def rotation_report(
    top_n: int = Query(default=10, ge=1, le=50),
) -> RotationReportModel:
    report = build_rotation_report(top_n=top_n)
    return RotationReportModel(
        radar_date=report.date,
        rankings=[RotationScoreModel(**item.to_dict()) for item in report.rankings],
        pools={
            name: [item.symbol for item in scores]
            for name, scores in report.pools.items()
        },
        data_notes=report.data_notes,
    )
