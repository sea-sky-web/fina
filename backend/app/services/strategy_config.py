"""Strategy configuration loader.

策略参数版本化：从 config/strategy.json 读取当前策略版本、参数和标的池路径。
文件缺失或字段不全时回退到 StrategyParams 的默认值（即 v58 参数），
保证 API 与 CLI 在无配置文件的环境下仍可运行。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.models import StrategyParams

STRATEGY_CONFIG_PATH = PROJECT_ROOT / "config" / "strategy.json"

_DEFAULT_UNIVERSE_FILE = "config/strategy_universe.csv"


@lru_cache(maxsize=1)
def _load_raw() -> dict:
    if not STRATEGY_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(STRATEGY_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_strategy_params() -> StrategyParams:
    raw = _load_raw()
    params = dict(raw.get("params", {}))
    if "version" in raw:
        params["version"] = raw["version"]
    return StrategyParams(**params)


def universe_path() -> Path:
    raw = _load_raw()
    rel = raw.get("universe_file", _DEFAULT_UNIVERSE_FILE)
    return PROJECT_ROOT / rel


def reload_strategy_config() -> None:
    """清空缓存，下次读取时重新加载 config/strategy.json（测试用）."""
    _load_raw.cache_clear()
