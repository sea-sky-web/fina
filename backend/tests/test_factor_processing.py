from datetime import date

import pandas as pd

from app.factors.processing import process_factor


def test_process_factor_requires_min_cross_section_size() -> None:
    values = pd.Series(
        [1.0, 2.0, 3.0],
        index=pd.MultiIndex.from_product(
            [[date(2026, 1, 1)], ["AAA.SH", "BBB.SH", "CCC.SH"]],
            names=["date", "symbol"],
        ),
    )

    processed = process_factor(values, min_cross_section_size=10)

    assert processed.isna().all()


def test_process_factor_keeps_large_enough_cross_section() -> None:
    values = pd.Series(
        range(10),
        index=pd.MultiIndex.from_product(
            [[date(2026, 1, 1)], [f"ETF{index}.SH" for index in range(10)]],
            names=["date", "symbol"],
        ),
        dtype="float64",
    )

    processed = process_factor(values, min_cross_section_size=10)

    assert processed.notna().sum() == 10
