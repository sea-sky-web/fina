from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_PATH = PROJECT_ROOT / "data" / "research" / "etf_daily_backtest.parquet"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"

TRADING_DAYS_PER_YEAR = 252


@dataclass
class StrategyConfig:
    # 基准
    benchmark: str = "510300.SH"

    # 交易成本与限制
    cost_rate_one_side: float = 0.00075
    max_symbol_weight: float = 0.25
    max_daily_turnover: float = 0.90
    circuit_breaker_daily_loss: float = -0.03

    # Walk-forward 窗口
    min_train_days: int = 250
    test_trading_days: int = 42
    step_trading_days: int = 21
    embargo_days: int = 1

    # 评分因子
    momentum_lookback_set: list[int] = field(default_factory=lambda: [10, 20])
    rel_strength_lookback: int = 60
    hysteresis_buffer: int = 3
    param_grid_k: list[int] = field(default_factory=lambda: [2, 3, 4])

    # 个股止损
    stop_loss_threshold: float = -0.05
    cooldown_days: int = 5

    # 组合回撤熔断
    portfolio_dd_threshold: float = -0.08
    portfolio_dd_cooldown: int = 5

    # 再入场
    reentry_bench_spike: float = 0.02
    reentry_consecutive_up: int = 2
    reentry_bench_days: int = 3
    reentry_peak_buffer: float = 0.04

    # 牛熊仓位缩放
    bear_scale: float = 0.50
    bull_boost: float = 1.50

    # 标的池过滤
    min_history_days: int = 1200
    min_avg_amount: float = 5.0e7

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_CONFIG = StrategyConfig()
