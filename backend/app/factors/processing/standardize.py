from __future__ import annotations

import pandas as pd


def zscore(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        return numeric

    std = valid.std(ddof=0)
    if pd.isna(std) or std == 0:
        return numeric.where(numeric.isna(), 0.0)
    return (numeric - valid.mean()) / std
