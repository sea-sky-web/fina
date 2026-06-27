from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class PerformanceAttribution:
    total_return: float = 0.0
    factor_contribution: dict[str, float] = field(default_factory=dict)
    specific_return: float = 0.0
    sector_contribution: dict[str, float] = field(default_factory=dict)
    r_squared: float = 0.0
    data_notes: list[str] = field(default_factory=list)


def attribute_performance(
    strategy_returns: pd.Series,
    factor_exposures: pd.DataFrame,
    *,
    min_obs: int = 30,
) -> PerformanceAttribution:
    """Decompose strategy returns into factor-driven and specific components.

    Args:
        strategy_returns: Daily strategy returns, index = date.
        factor_exposures: Daily factor percentile exposures, index = date,
            columns = factor names.
        min_obs: Minimum overlapping observations for regression.

    Returns:
        PerformanceAttribution with factor contributions and R-squared.
    """
    aligned = pd.concat(
        [
            pd.to_numeric(strategy_returns, errors="coerce").rename("strategy"),
            factor_exposures.apply(pd.to_numeric, errors="coerce"),
        ],
        axis=1,
    ).dropna()

    if len(aligned) < min_obs or aligned.shape[1] < 2:
        return PerformanceAttribution(
            total_return=float(strategy_returns.sum()) if not strategy_returns.empty else 0.0,
            data_notes=["样本不足或因子暴露缺失，跳过收益归因。"],
        )

    X = aligned.drop(columns="strategy")
    X = X.loc[:, X.std(ddof=0) > 0]
    if X.empty:
        return PerformanceAttribution(
            total_return=float(aligned["strategy"].sum()),
            data_notes=["所有因子暴露方差为 0，无法回归。"],
        )

    y = aligned["strategy"]
    X_const = np.column_stack([np.ones(len(X)), X.to_numpy()])
    coeffs, residuals, rank, _ = np.linalg.lstsq(X_const, y.to_numpy(), rcond=None)

    ss_total = float(np.sum((y - y.mean()) ** 2))
    ss_residual = float(np.sum(residuals)) if len(residuals) > 0 else ss_total
    r_squared = 1 - ss_residual / ss_total if ss_total > 0 else 0.0

    total_return = float(y.sum())
    factor_contrib = {}
    for idx, factor_name in enumerate(X.columns):
        contrib = float(coeffs[idx + 1] * X[factor_name].sum())
        factor_contrib[factor_name] = contrib

    explained_return = sum(factor_contrib.values())
    specific_return = total_return - explained_return

    return PerformanceAttribution(
        total_return=total_return,
        factor_contribution=factor_contrib,
        specific_return=specific_return,
        r_squared=r_squared,
        data_notes=[
            f"因子模型 R² = {r_squared:.3f}",
            "归因基于日收益回归因子暴露，仅反映历史统计关系。",
        ],
    )
