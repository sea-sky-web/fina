from __future__ import annotations

import pandas as pd


def winsorize_mad(values: pd.Series, mad_n: float = 5.0) -> pd.Series:
    """Clip a cross section with the robust MAD rule."""
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        return numeric

    median = valid.median()
    mad = (valid - median).abs().median()
    if pd.isna(mad) or mad == 0:
        return numeric

    radius = mad_n * 1.4826 * mad
    return numeric.clip(lower=median - radius, upper=median + radius)


def winsorize_percentile(
    values: pd.Series,
    lower: float = 0.01,
    upper: float = 0.99,
) -> pd.Series:
    """Clip a cross section at fixed quantiles."""
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        return numeric
    return numeric.clip(lower=valid.quantile(lower), upper=valid.quantile(upper))


def winsorize_by_method(
    values: pd.Series,
    method: str = "mad",
    mad_n: float = 5.0,
) -> pd.Series:
    if method == "none":
        return pd.to_numeric(values, errors="coerce")
    if method == "percentile":
        return winsorize_percentile(values)
    return winsorize_mad(values, mad_n=mad_n)
