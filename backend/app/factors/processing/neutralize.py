from __future__ import annotations

import pandas as pd

from app.factors.processing.standardize import zscore


def intra_group_rank(values: pd.Series, groups: pd.Series) -> pd.Series:
    """
    Convert each date cross section into favorable within-theme percentile ranks.

    The input values must already use a higher-is-better orientation. Callers should
    route raw factor values through process_factor(..., direction=...) instead of
    invoking this function directly.
    """
    aligned_groups = groups.reindex(values.index)
    output = pd.Series(index=values.index, dtype="float64")

    for group_name in aligned_groups.dropna().unique():
        mask = aligned_groups == group_name
        group_values = pd.to_numeric(values[mask], errors="coerce")
        valid_count = int(group_values.notna().sum())
        if valid_count == 0:
            continue
        if valid_count == 1:
            output.loc[group_values.index[group_values.notna()]] = 0.5
            continue
        output.loc[group_values.index] = group_values.rank(ascending=False, pct=True)

    missing_group_values = values[aligned_groups.isna()]
    if not missing_group_values.empty:
        output.loc[missing_group_values.index] = missing_group_values.rank(
            ascending=False,
            pct=True,
        )

    return output


def residual_neutralize(values: pd.Series, groups: pd.Series) -> pd.Series:
    """Subtract date-local group means, then re-standardize the remaining exposure."""
    aligned_groups = groups.reindex(values.index)
    numeric = pd.to_numeric(values, errors="coerce")
    group_mean = numeric.groupby(aligned_groups, dropna=False).transform("mean")
    return zscore(numeric - group_mean)


def neutralize_by_method(
    values: pd.Series,
    groups: pd.Series,
    method: str = "intra_group_rank",
) -> pd.Series:
    if method == "residual":
        return residual_neutralize(values, groups)
    return intra_group_rank(values, groups)
