"""V58 strategy portfolio state persistence.

Stores entry prices, cooldown timers, current holdings between signal runs.
Uses atomic JSON file writes matching the existing normalizer pattern.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from app.core.config import settings

STATE_FILE = Path(settings.clean_dir) / "v58_state.json"


@dataclass
class V58PersistentState:
    last_signal_date: str | None = None
    entry_prices: dict[str, float] = field(default_factory=dict)
    cooldown_until: dict[str, str] = field(default_factory=dict)
    current_holdings: list[str] = field(default_factory=list)
    portfolio_equity: float = 1.0
    portfolio_peak: float = 1.0


def load_state() -> V58PersistentState:
    if not STATE_FILE.exists():
        return V58PersistentState()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return V58PersistentState(**data)
    except Exception:
        return V58PersistentState()


def save_state(state: V58PersistentState) -> None:
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
    if STATE_FILE.exists():
        STATE_FILE.unlink()
