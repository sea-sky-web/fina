from datetime import UTC, date, datetime

from app.models import (
    FactorCorrelationMatrix,
    FactorEvaluationReport,
    FactorICStats,
    RedundantFactorPair,
)
from app.synthesis import FALLBACK_SIGNAL_WEIGHTS, filter_factors, icir_weights


def _report(name: str, icir: float, pos_ratio: float = 0.60) -> FactorEvaluationReport:
    return FactorEvaluationReport(
        factor_name=name,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        num_assets_avg=100,
        ic=FactorICStats(
            factor_name=name,
            num_periods=50,
            rank_ic_mean=0.03,
            rank_ic_std=0.1,
            icir=icir,
            ic_pos_ratio=pos_ratio,
            ic_t_stat=2.0,
        ),
    )


def test_filter_factors_removes_weaker_high_correlation_duplicate() -> None:
    reports = [
        _report("momentum_60d", 0.35),
        _report("risk_adjusted_return_60d", 0.25),
        _report("volatility_30d", 0.10),
    ]
    matrix = FactorCorrelationMatrix(
        factor_names=["momentum_60d", "risk_adjusted_return_60d", "volatility_30d"],
        redundant_pairs=[
            RedundantFactorPair(
                factor_a="momentum_60d",
                factor_b="risk_adjusted_return_60d",
                correlation=0.82,
            )
        ],
    )

    selected = filter_factors(reports, matrix)

    assert selected == ["momentum_60d"]


def test_icir_weights_apply_correlation_penalty_and_normalize() -> None:
    reports = [
        _report("momentum_60d", 0.40),
        _report("liquidity_stability_20d", 0.20),
    ]
    matrix = FactorCorrelationMatrix(
        factor_names=["momentum_60d", "liquidity_stability_20d"],
        redundant_pairs=[
            RedundantFactorPair(
                factor_a="momentum_60d",
                factor_b="liquidity_stability_20d",
                correlation=0.65,
            )
        ],
    )

    weights = icir_weights(reports, matrix)

    assert set(weights) == {"momentum_60d", "liquidity_stability_20d"}
    assert round(sum(weights.values()), 8) == 1
    assert weights["momentum_60d"] > weights["liquidity_stability_20d"]


def test_icir_weights_fall_back_when_quality_gate_fails() -> None:
    weights = icir_weights([_report("momentum_60d", 0.05, pos_ratio=0.40)])

    assert weights == FALLBACK_SIGNAL_WEIGHTS
