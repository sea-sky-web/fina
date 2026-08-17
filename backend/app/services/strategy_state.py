"""Strategy portfolio state persistence.

Stores entry prices, cooldown timers, current holdings between signal runs.
Uses atomic JSON file writes matching the existing normalizer pattern.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.core.config import settings

STATE_FILE = Path(settings.clean_dir) / "strategy_state.json"
# 旧版状态文件（v58 硬编码时代），仅用于一次性迁移读取
_LEGACY_STATE_FILE = Path(settings.clean_dir) / "v58_state.json"


@dataclass
class StrategyPersistentState:
    last_signal_date: str | None = None
    entry_prices: dict[str, float] = field(default_factory=dict)
    cooldown_until: dict[str, str] = field(default_factory=dict)
    current_holdings: list[str] = field(default_factory=list)
    portfolio_equity: float = 1.0
    portfolio_peak: float = 1.0


def load_state() -> StrategyPersistentState:
    for path in (STATE_FILE, _LEGACY_STATE_FILE):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return StrategyPersistentState(**data)
        except Exception:
            continue
    return StrategyPersistentState()


def save_state(state: StrategyPersistentState) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(STATE_FILE.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(state), f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(STATE_FILE))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def reset_state() -> None:
    for path in (STATE_FILE, _LEGACY_STATE_FILE):
        if path.exists():
            path.unlink()
