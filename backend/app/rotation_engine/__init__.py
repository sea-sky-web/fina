"""ETF 轮动回测策略 — 支持单类和多资产模式."""

__version__ = "2.0.0"

from .asset_class import AssetClass, classify_etf
from .config import DEFAULT_CONFIG, DEFAULT_MULTI_CONFIG, MultiAssetConfig, StrategyConfig

__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_MULTI_CONFIG",
    "AssetClass",
    "MultiAssetConfig",
    "StrategyConfig",
    "classify_etf",
]
