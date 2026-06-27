from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Factor(ABC):
    name: str
    label: str
    description: str
    lookback_days: int
    direction: str = "higher_better"
    category: str = "return"
    value_format: str = "percent"
    interpretation: str = ""

    @abstractmethod
    def compute(self, daily: pd.DataFrame) -> pd.Series:
        """Return factor_value Series with the same index as daily."""
