from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.factors.base import Factor


class EpsRevision(Factor):
    name = "eps_revision"
    label = "一致预期修正率"
    description = "行业龙头股EPS一致预期的加权平均，作为景气代理"
    lookback_days = 1
    direction = "higher_better"
    category = "fundamental"
    value_format = "score"
    interpretation = "EPS一致预期越高的行业=景气越好=得分高。跨期修正需持续采集历史快照。"

    CONSENSUS_PATH = Path("data/clean/consensus_eps.json")

    # ETF代码 → 主题映射（与theme_classifier一致）
    ETF_THEME_MAP = {
        "159995.SZ": "半导体芯片",
        "512480.SH": "半导体芯片",
        "512880.SH": "金融地产",
        "512800.SH": "金融地产",
        "512000.SH": "金融地产",
        "159992.SZ": "医药医疗",
        "512010.SH": "医药医疗",
        "159928.SZ": "消费",
        "518880.SH": "资源能源",
        "515220.SH": "资源能源",
        "159870.SZ": "资源能源",
        "159530.SZ": "科技AI",
    }

    def compute(self, daily: pd.DataFrame) -> pd.Series:
        theme_scores = self._load_theme_scores()
        if not theme_scores:
            return pd.Series(float("nan"), index=daily.index)

        from app.services.theme_classifier import infer_etf_theme
        from app.storage.parquet_store import read_parquet
        from app.core.config import settings

        basic = read_parquet(settings.clean_dir / "etf_basic.parquet")
        symbol_theme = {}
        for _, row in basic.iterrows():
            sym = row["symbol"]
            name = str(row.get("name", ""))
            idx = str(row.get("index_name", "")) if pd.notna(row.get("index_name")) else ""
            symbol_theme[sym] = infer_etf_theme(name, idx)

        result = pd.Series(float("nan"), index=daily.index)
        for i, row in daily.iterrows():
            sym = row["symbol"]
            theme = symbol_theme.get(sym)
            if theme and theme in theme_scores:
                result.iloc[i] = theme_scores[theme]

        return result

    def _load_theme_scores(self) -> dict[str, float]:
        if not self.CONSENSUS_PATH.exists():
            return {}

        with open(self.CONSENSUS_PATH, encoding="utf-8") as f:
            data = json.load(f)

        theme_eps = data.get("theme_eps", {})
        if not theme_eps:
            return {}

        scores = {}
        all_eps = []
        for theme, info in theme_eps.items():
            if not info.get("stocks"):
                continue
            total_w = info["total_weight"]
            if total_w <= 0:
                continue
            weighted = sum(
                s["weight"] * s["eps_consensus"]
                for s in info["stocks"]
            ) / total_w
            scores[theme] = weighted
            all_eps.append(weighted)

        if not all_eps:
            return {}

        min_eps = min(all_eps)
        max_eps = max(all_eps)
        rng = max_eps - min_eps
        if rng <= 0:
            return {t: 50.0 for t in scores}

        return {
            theme: (val - min_eps) / rng * 80 + 10
            for theme, val in scores.items()
        }
