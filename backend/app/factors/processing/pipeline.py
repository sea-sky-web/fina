from __future__ import annotations

import pandas as pd

from app.factors.processing.neutralize import neutralize_by_method
from app.factors.processing.outliers import winsorize_by_method
from app.factors.processing.standardize import zscore


def _by_date(values: pd.Series, transform) -> pd.Series:
    if not isinstance(values.index, pd.MultiIndex) or "date" not in values.index.names:
        return transform(values)
    return values.groupby(level="date", group_keys=False).apply(transform)


def _require_min_cross_section(values: pd.Series, min_size: int) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if int(numeric.notna().sum()) < min_size:
        return pd.Series(index=values.index, dtype="float64")
    return numeric


def _expand_symbol_groups(index: pd.MultiIndex, groupby: pd.Series) -> pd.Series:
    symbol_level = index.names.index("symbol")
    symbols = pd.Series(index.get_level_values(symbol_level), index=index)
    return symbols.map(groupby.to_dict())


def process_factor(
    factor_values: pd.Series,
    *,
    direction: str = "higher_better",
    method: str = "mad",
    mad_n: float = 5.0,
    standardize: bool = True,
    groupby: pd.Series | None = None,
    neutralize_method: str = "intra_group_rank",
    min_cross_section_size: int = 10,
) -> pd.Series:
    """Run the ETF factor processing pipeline on date-symbol indexed values."""
    values = pd.to_numeric(factor_values, errors="coerce")
    if direction == "lower_better":
        values = -values

    values = _by_date(
        values,
        lambda group: _require_min_cross_section(group, min_cross_section_size),
    )
    processed = _by_date(
        values,
        lambda group: winsorize_by_method(group, method=method, mad_n=mad_n),
    )
    if standardize:
        processed = _by_date(processed, zscore)

    if groupby is not None and isinstance(processed.index, pd.MultiIndex):
        groups = _expand_symbol_groups(processed.index, groupby)
        processed = processed.groupby(level="date", group_keys=False).apply(
            lambda group: neutralize_by_method(
                group,
                groups.reindex(group.index),
                method=neutralize_method,
            )
        )

    return processed.reindex(factor_values.index)
