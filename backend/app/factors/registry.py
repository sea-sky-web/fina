from __future__ import annotations

from app.factors.base import Factor
from app.factors.drawdown import MaxDrawdown60D
from app.factors.liquidity_stability import LiquidityStability20D
from app.factors.momentum import Momentum60D
from app.factors.risk_adjusted_return import RiskAdjustedReturn60D
from app.factors.trend_strength import TrendStrength20To60D
from app.factors.turnover import Turnover20D
from app.factors.volatility import Volatility30D

FACTOR_REGISTRY: dict[str, Factor] = {
    Momentum60D.name: Momentum60D(),
    Volatility30D.name: Volatility30D(),
    Turnover20D.name: Turnover20D(),
    MaxDrawdown60D.name: MaxDrawdown60D(),
    RiskAdjustedReturn60D.name: RiskAdjustedReturn60D(),
    LiquidityStability20D.name: LiquidityStability20D(),
    TrendStrength20To60D.name: TrendStrength20To60D(),
}
