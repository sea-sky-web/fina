from __future__ import annotations

from app.models import FactorCorrelationMatrix, FactorEvaluationReport


def _report_quality(report: FactorEvaluationReport) -> tuple[float, float]:
    icir = report.ic.icir or 0.0
    pos_ratio = report.ic.ic_pos_ratio or 0.0
    return icir, pos_ratio


def filter_factors(
    evaluation_reports: list[FactorEvaluationReport],
    correlation_matrix: FactorCorrelationMatrix | None = None,
    *,
    min_icir: float = 0.2,
    min_ic_pos_ratio: float = 0.55,
    max_pairwise_corr: float = 0.75,
) -> list[str]:
    """Keep factors with enough IC quality, then drop weaker high-correlation duplicates."""
    reports_by_name = {report.factor_name: report for report in evaluation_reports}
    selected = [
        report.factor_name
        for report in evaluation_reports
        if (report.ic.icir or 0.0) >= min_icir
        and (report.ic.ic_pos_ratio or 0.0) >= min_ic_pos_ratio
    ]
    if not selected:
        return []

    if correlation_matrix is None:
        return selected

    remaining = selected.copy()
    for pair in correlation_matrix.redundant_pairs:
        if abs(pair.correlation) < max_pairwise_corr:
            continue
        if pair.factor_a not in remaining or pair.factor_b not in remaining:
            continue

        left_quality = _report_quality(reports_by_name[pair.factor_a])
        right_quality = _report_quality(reports_by_name[pair.factor_b])
        loser = pair.factor_b if left_quality >= right_quality else pair.factor_a
        remaining.remove(loser)

    return remaining
