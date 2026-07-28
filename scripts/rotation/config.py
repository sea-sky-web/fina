from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .asset_class import AssetClass

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_PATH = PROJECT_ROOT / "data" / "research" / "etf_daily_backtest.parquet"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"

TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# Legacy single-class config (fully preserved for backward compat)
# ---------------------------------------------------------------------------

@dataclass
class StrategyConfig:
    benchmark: str = "510300.SH"

    cost_rate_one_side: float = 0.00075
    max_symbol_weight: float = 0.25
    max_daily_turnover: float = 0.90
    circuit_breaker_daily_loss: float = -0.03

    min_train_days: int = 250
    test_trading_days: int = 42
    step_trading_days: int = 21
    embargo_days: int = 1

    momentum_lookback_set: list[int] = field(default_factory=lambda: [10, 20])
    rel_strength_lookback: int = 60
    hysteresis_buffer: int = 3
    param_grid_k: list[int] = field(default_factory=lambda: [2, 3, 4])

    stop_loss_threshold: float = -0.05
    cooldown_days: int = 5

    portfolio_dd_threshold: float = -0.08
    portfolio_dd_cooldown: int = 5

    reentry_bench_spike: float = 0.02
    reentry_consecutive_up: int = 2
    reentry_bench_days: int = 3
    reentry_peak_buffer: float = 0.04

    bear_scale: float = 0.50
    bull_boost: float = 1.00

    min_history_days: int = 1200
    min_avg_amount: float = 5.0e7

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_CONFIG = StrategyConfig()


# ---------------------------------------------------------------------------
# Multi-asset per-class config
# ---------------------------------------------------------------------------

@dataclass
class ClassConfig:
    """Layer 2 参数 — 每个资产大类独立一份."""
    benchmark: str = "510300.SH"

    cost_rate_one_side: float = 0.00075
    max_symbol_weight: float = 0.35
    max_daily_turnover: float = 0.90

    momentum_lookback_set: list[int] = field(default_factory=lambda: [10, 20])
    rel_strength_lookback: int = 60
    hysteresis_buffer: int = 3
    param_grid_k: list[int] = field(default_factory=lambda: [2, 3])

    stop_loss_threshold: float = -0.05
    cooldown_days: int = 5
    circuit_breaker_daily_loss: float = -0.03

    portfolio_dd_threshold: float = -0.08
    portfolio_dd_cooldown: int = 5
    reentry_bench_spike: float = 0.02
    reentry_consecutive_up: int = 2
    reentry_bench_days: int = 3
    reentry_peak_buffer: float = 0.04

    bear_scale: float = 0.50
    bull_boost: float = 1.00

    min_history_days: int = 500
    min_avg_amount: float = 1.0e7


DEFAULT_CLASS_CONFIGS: dict[AssetClass, ClassConfig] = {
    AssetClass.EQUITY_SECTOR: ClassConfig(
        benchmark="510300.SH",
        momentum_lookback_set=[10, 20],
        rel_strength_lookback=60,
        param_grid_k=[2, 3, 4],
        stop_loss_threshold=-0.05,
        circuit_breaker_daily_loss=-0.03,
        bear_scale=0.50,
        bull_boost=1.00,
        min_history_days=1200,
        min_avg_amount=5.0e7,
    ),
    AssetClass.EQUITY_BROAD: ClassConfig(
        benchmark="510300.SH",
        momentum_lookback_set=[10, 20],
        rel_strength_lookback=60,
        param_grid_k=[1, 2],
        stop_loss_threshold=-0.06,
        circuit_breaker_daily_loss=-0.04,
        bear_scale=0.50,
        bull_boost=1.00,
        min_history_days=500,
        min_avg_amount=5.0e7,
    ),
    AssetClass.BOND: ClassConfig(
        benchmark="511010.SH",
        momentum_lookback_set=[20, 40],
        rel_strength_lookback=40,
        param_grid_k=[1, 2],
        stop_loss_threshold=-0.03,
        cooldown_days=10,
        circuit_breaker_daily_loss=-0.02,
        portfolio_dd_threshold=-0.04,
        bear_scale=0.70,
        bull_boost=1.00,
        min_history_days=500,
        min_avg_amount=1.0e7,
    ),
    AssetClass.COMMODITY: ClassConfig(
        benchmark="518880.SH",
        momentum_lookback_set=[10, 20],
        rel_strength_lookback=30,
        param_grid_k=[1, 2],
        stop_loss_threshold=-0.10,
        circuit_breaker_daily_loss=-0.06,
        portfolio_dd_threshold=-0.12,
        bear_scale=0.50,
        bull_boost=1.00,
        min_history_days=500,
        min_avg_amount=1.0e7,
    ),
    AssetClass.CROSS_BORDER: ClassConfig(
        benchmark="513050.SH",
        momentum_lookback_set=[10, 20],
        rel_strength_lookback=40,
        param_grid_k=[1, 2, 3],
        stop_loss_threshold=-0.08,
        circuit_breaker_daily_loss=-0.05,
        portfolio_dd_threshold=-0.10,
        bear_scale=0.50,
        bull_boost=1.00,
        min_history_days=500,
        min_avg_amount=1.0e7,
    ),
}


@dataclass
class MacroConfig:
    """Layer 1 宏观资产配置参数."""
    trend_ma_short: int = 10
    trend_ma_long: int = 30
    momentum_lookback: int = 60
    safe_haven: AssetClass = AssetClass.BOND
    base_weights: dict[AssetClass, float] = field(default_factory=lambda: {
        AssetClass.EQUITY_SECTOR: 0.30,
        AssetClass.EQUITY_BROAD: 0.15,
        AssetClass.BOND: 0.20,
        AssetClass.COMMODITY: 0.15,
        AssetClass.CROSS_BORDER: 0.20,
    })


@dataclass
class MultiAssetConfig:
    """顶层多资产配置."""
    macro: MacroConfig = field(default_factory=MacroConfig)
    class_configs: dict[AssetClass, ClassConfig] = field(
        default_factory=lambda: dict(DEFAULT_CLASS_CONFIGS),
    )

    # walk-forward 参数（全局共享）
    min_train_days: int = 250
    test_trading_days: int = 42
    step_trading_days: int = 21
    embargo_days: int = 1

    def enabled_classes(self) -> list[AssetClass]:
        return list(self.class_configs.keys())


DEFAULT_MULTI_CONFIG = MultiAssetConfig()
