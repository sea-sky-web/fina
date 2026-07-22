"""ETF 轮动回测策略 — 支持单类和多资产模式."""

__version__ = "2.0.0"

from .config import StrategyConfig, DEFAULT_CONFIG, MultiAssetConfig, DEFAULT_MULTI_CONFIG
from .asset_class import AssetClass, classify_etf
