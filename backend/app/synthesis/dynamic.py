from __future__ import annotations

from app.factors.registry import FACTOR_REGISTRY

RISK_FACTOR_NAMES = {
    "volatility_30d",
    "max_drawdown_60d",
    "liquidity_stability_20d",
    "turnover_20d",
}
RETURN_FACTOR_NAMES = {"momentum_60d", "risk_adjusted_return_60d", "trend_strength_20_60d"}


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(value for value in weights.values() if value > 0)
    if total <= 0:
        return {}
    return {name: value / total for name, value in weights.items() if value > 0}


def adjust_weights_for_regime(
    weights: dict[str, float],
    regime_label: str,
) -> tuple[dict[str, float], str]:
    """Tilt factor weights by market regime while preserving the selected factor set."""
    if not weights:
        return {}, "无可用因子权重。"

    multipliers: dict[str, float] = {}
    for name in weights:
        if name not in FACTOR_REGISTRY:
            multipliers[name] = 1.0
            continue
        if regime_label == "risk_off":
            multipliers[name] = 1.30 if name in RISK_FACTOR_NAMES else 0.85
        elif regime_label == "risk_on":
            multipliers[name] = 1.15 if name in RETURN_FACTOR_NAMES else 0.92
        else:
            multipliers[name] = 1.0

    adjusted = _normalize({name: weight * multipliers[name] for name, weight in weights.items()})
    if regime_label == "risk_off":
        note = "防御状态下动态提高低波动、低回撤和流动性稳定因子的权重。"
    elif regime_label == "risk_on":
        note = "风险偏好状态下动态提高动量、趋势和风险调整收益因子的权重。"
    else:
        note = "中性状态下保持基础因子权重。"
    return adjusted or weights.copy(), note
