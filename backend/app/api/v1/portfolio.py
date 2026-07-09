from fastapi import APIRouter

from app.models import PortfolioAdviceReport, PortfolioAdviceRequest
from app.services.portfolio_advice_service import build_portfolio_advice

router = APIRouter()


@router.post("/advice", response_model=PortfolioAdviceReport)
def portfolio_advice(request: PortfolioAdviceRequest) -> PortfolioAdviceReport:
    return build_portfolio_advice(request)
