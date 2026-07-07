from __future__ import annotations

from app.models import FactorCorrelationMatrix, FactorEvaluationReport
from app.synthesis.selection import filter_factors

FALLBACK_SIGNAL_WEIGHTS: dict[str, float] = {
    "momentum_60d": 0.13,
    "risk_adjusted_return_60d": 0.13,
    "trend_strength_20_60d": 0.09,
    "turnover_20d": 0.08,
    "liquidity_stability_20d": 0.08,
    "volatility_30d": 0.07,
    "max_drawdown_60d": 0.05,
    "reversal_5d": 0.07,
    "rsi_14d": 0.05,
    "momentum_exhaustion": 0.05,
    "turnover_concentration": 0.05,
    "deviation_rate_60d": 0.05,
    "eps_revision": 0.10,
}


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(value for value in weights.values() if value > 0)
    if total <= 0:
        return {}
    return {name: value / total for name, value in weights.items() if value > 0}


def _average_abs_correlation(
    factor_name: str,
    selected_names: set[str],
    correlation_matrix: FactorCorrelationMatrix | None,
) -> float:
    if correlation_matrix is None:
        return 0.0

    correlations = [
        abs(pair.correlation)
        for pair in correlation_matrix.redundant_pairs
        if (
            pair.factor_a == factor_name
            and pair.factor_b in selected_names
        )
        or (
            pair.factor_b == factor_name
            and pair.factor_a in selected_names
        )
    ]
    if not correlations:
        return 0.0
    return sum(correlations) / len(correlations)


def icir_weights(
    evaluation_reports: list[FactorEvaluationReport],
    correlation_matrix: FactorCorrelationMatrix | None = None,
    *,
    min_icir: float = 0.2,
    min_ic_pos_ratio: float = 0.55,
    min_factors: int = 3,
) -> dict[str, float]:
    """Build ICIR-based weights with a simple high-correlation penalty."""
    selected = filter_factors(
        evaluation_reports,
        correlation_matrix,
        min_icir=min_icir,
        min_ic_pos_ratio=min_ic_pos_ratio,
    )
    if len(selected) < min_factors:
        return FALLBACK_SIGNAL_WEIGHTS.copy()

    reports_by_name = {report.factor_name: report for report in evaluation_reports}
    selected_names = set(selected)
    raw_weights: dict[str, float] = {}
    for name in selected:
        icir = max(reports_by_name[name].ic.icir or 0.0, 0.0)
        corr_penalty = 1 - 0.5 * _average_abs_correlation(
            name,
            selected_names,
            correlation_matrix,
        )
        raw_weights[name] = max(icir * corr_penalty, 0.0)

    normalized = _normalize(raw_weights)
    if normalized:
        return normalized

    equal_weight = 1 / len(selected)
    return {name: equal_weight for name in selected}
