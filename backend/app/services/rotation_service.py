from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import sqrt
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import settings
from app.services.records import dataframe_records
from app.services.theme_classifier import infer_etf_theme
from app.storage.parquet_store import read_parquet

TRADING_DAYS_PER_YEAR = 252
BENCHMARK_SYMBOL = "510300.SH"


@dataclass(frozen=True)
class RotationInputs:
    symbol: str | None
    theme: str
    etf_type: str
    boom_status: str = "不确定"
    boom_score: float = 50.0
    valuation_percentile: float = 50.0
    structure_score: float = 60.0
    notes: str = ""


@dataclass(frozen=True)
class RotationScore:
    symbol: str
    name: str
    theme: str
    etf_type: str
    date: date
    total_score: float
    boom_score: float
    momentum_score: float
    valuation_score: float
    structure_score: float
    liquidity_score: float
    risk_score: float
    boom_status: str
    valuation_percentile: float
    state: str
    action: str
    returns: dict[str, float | None] = field(default_factory=dict)
    risk_notes: list[str] = field(default_factory=list)
    drivers: list[str] = field(default_factory=list)
    input_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "theme": self.theme,
            "etf_type": self.etf_type,
            "date": self.date.isoformat(),
            "total_score": self.total_score,
            "boom_score": self.boom_score,
            "momentum_score": self.momentum_score,
            "valuation_score": self.valuation_score,
            "structure_score": self.structure_score,
            "liquidity_score": self.liquidity_score,
            "risk_score": self.risk_score,
            "boom_status": self.boom_status,
            "valuation_percentile": self.valuation_percentile,
            "state": self.state,
            "action": self.action,
            "returns": self.returns,
            "risk_notes": self.risk_notes,
            "drivers": self.drivers,
            "input_notes": self.input_notes,
        }


@dataclass(frozen=True)
class RotationReport:
    date: date | None
    rankings: list[RotationScore]
    pools: dict[str, list[RotationScore]]
    data_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat() if self.date else None,
            "rankings": [item.to_dict() for item in self.rankings],
            "pools": {
                name: [item.symbol for item in scores]
                for name, scores in self.pools.items()
            },
            "data_notes": self.data_notes,
        }


def _clip_score(value: float | int | None, default: float = 50.0) -> float:
    if value is None or pd.isna(value):
        return default
    return float(max(0.0, min(100.0, float(value))))


def infer_etf_type(name: str | None, theme: str) -> str:
    text = f"{name or ''}{theme}".upper()
    if theme == "货币现金" or any(keyword in text for keyword in ["货币", "债", "国债", "政金债"]):
        return "货币债券"
    if theme in {"宽基指数", "科创创业", "海外指数"}:
        return "宽基"
    if theme in {"红利低波"} or any(
        keyword in text for keyword in ["红利", "低波", "价值", "质量"]
    ):
        return "风格"
    if theme in {"科技AI", "新能源", "港股中概"}:
        return "主题"
    if theme in {"半导体芯片", "医药医疗", "金融地产", "资源能源", "消费"}:
        return "行业"
    return "其他"


def _load_rotation_inputs(
    path: Path | str | None = None,
) -> tuple[dict[str, RotationInputs], dict[str, RotationInputs]]:
    source = Path(path) if path is not None else settings.rotation_input_path
    if not source.exists():
        return {}, {}
    frame = pd.read_csv(source).astype("object").where(pd.notna, None)
    by_symbol: dict[str, RotationInputs] = {}
    by_theme: dict[str, RotationInputs] = {}
    for row in frame.to_dict(orient="records"):
        item = RotationInputs(
            symbol=str(row.get("symbol")) if row.get("symbol") else None,
            theme=str(row.get("theme") or "其他"),
            etf_type=str(row.get("etf_type") or "其他"),
            boom_status=str(row.get("boom_status") or "不确定"),
            boom_score=_clip_score(row.get("boom_score")),
            valuation_percentile=_clip_score(row.get("valuation_percentile")),
            structure_score=_clip_score(row.get("structure_score"), default=60.0),
            notes=str(row.get("notes") or ""),
        )
        if item.symbol:
            by_symbol[item.symbol] = item
        else:
            by_theme[item.theme] = item
    return by_symbol, by_theme


def _clean_daily() -> pd.DataFrame:
    daily = read_parquet(settings.clean_dir / "etf_daily.parquet")
    required = {"symbol", "date", "close"}
    if daily.empty or not required.issubset(daily.columns):
        return pd.DataFrame(columns=["symbol", "date", "close", "amount"])
    columns = [
        column
        for column in ["symbol", "date", "close", "amount"]
        if column in daily.columns
    ]
    frame = daily[columns].copy()
    if "amount" not in frame.columns:
        frame["amount"] = pd.NA
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    return frame.dropna(subset=["symbol", "date", "close"]).sort_values(["symbol", "date"])


def _basic_lookup() -> dict[str, dict[str, Any]]:
    basic = read_parquet(settings.clean_dir / "etf_basic.parquet")
    if basic.empty or "symbol" not in basic.columns:
        return {}
    keep = [column for column in ["symbol", "name", "index_name"] if column in basic.columns]
    return {record["symbol"]: record for record in dataframe_records(basic[keep].copy())}


def _period_return(series: pd.Series, periods: int) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) <= periods:
        return None
    base = float(clean.iloc[-periods - 1])
    latest = float(clean.iloc[-1])
    if base <= 0:
        return None
    return latest / base - 1


def _average_amount(series: pd.Series, window: int = 20) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return None
    return float(clean.tail(window).mean())


def _amount_growth(series: pd.Series, window: int = 20) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) < window * 2:
        return None
    recent = float(clean.tail(window).mean())
    previous = float(clean.iloc[-window * 2 : -window].mean())
    if previous <= 0:
        return None
    return recent / previous - 1


def _moving_average_status(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return 50.0
    latest = float(clean.iloc[-1])
    score = 0.0
    weights = {20: 40.0, 60: 35.0, 120: 25.0}
    available = 0.0
    for window, weight in weights.items():
        if len(clean) < window:
            continue
        available += weight
        if latest >= float(clean.tail(window).mean()):
            score += weight
    return 50.0 if available == 0 else score / available * 100


def _volatility(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    returns = clean.pct_change(fill_method=None).dropna().tail(20)
    if returns.empty:
        return None
    return float(returns.std(ddof=0) * sqrt(TRADING_DAYS_PER_YEAR))


def _drawdown(series: pd.Series, window: int = 60) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna().tail(window)
    if clean.empty:
        return None
    high = float(clean.max())
    latest = float(clean.iloc[-1])
    if high <= 0:
        return None
    return latest / high - 1


def _score_from_risk(
    volatility: float | None,
    drawdown: float | None,
    return_3m: float | None,
) -> float:
    vol_score = 70.0 if volatility is None else 100 - min(max(volatility, 0.0), 0.60) / 0.60 * 70
    drawdown_score = (
        70.0
        if drawdown is None
        else 100 - min(abs(min(drawdown, 0.0)), 0.30) / 0.30 * 70
    )
    score = 0.55 * vol_score + 0.45 * drawdown_score
    if return_3m is not None and return_3m > 0.30:
        score -= 8
    return _clip_score(score)


def _percentile(
    values: pd.Series,
    *,
    higher_better: bool = True,
    default: float = 50.0,
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() < 2:
        return pd.Series(default, index=values.index, dtype="float64")
    ranked = numeric.rank(ascending=higher_better, pct=True) * 100
    return ranked.fillna(default)


def _relative_return(value: float | None, benchmark: float | None) -> float | None:
    if value is None or benchmark is None:
        return None
    return value - benchmark


def _metric_frame(daily: pd.DataFrame) -> tuple[pd.DataFrame, date | None]:
    if daily.empty:
        return pd.DataFrame(), None
    target_date = max(daily["date"])
    prices = daily.pivot_table(
        index="date",
        columns="symbol",
        values="close",
        aggfunc="last",
    ).sort_index()
    amounts = daily.pivot_table(
        index="date",
        columns="symbol",
        values="amount",
        aggfunc="last",
    ).sort_index()
    benchmark = prices.get(BENCHMARK_SYMBOL)
    benchmark_returns = {
        "return_1m": _period_return(benchmark, 21) if benchmark is not None else None,
        "return_3m": _period_return(benchmark, 63) if benchmark is not None else None,
        "return_6m": _period_return(benchmark, 126) if benchmark is not None else None,
    }

    rows: list[dict[str, Any]] = []
    for symbol in prices.columns:
        series = prices[symbol]
        amount_series = amounts[symbol] if symbol in amounts.columns else pd.Series(dtype="float64")
        return_1m = _period_return(series, 21)
        return_3m = _period_return(series, 63)
        return_6m = _period_return(series, 126)
        rows.append(
            {
                "symbol": symbol,
                "return_1m": return_1m,
                "return_3m": return_3m,
                "return_6m": return_6m,
                "relative_1m": _relative_return(return_1m, benchmark_returns["return_1m"]),
                "relative_3m": _relative_return(return_3m, benchmark_returns["return_3m"]),
                "relative_6m": _relative_return(return_6m, benchmark_returns["return_6m"]),
                "ma_score": _moving_average_status(series),
                "amount_20d": _average_amount(amount_series),
                "amount_growth_20d": _amount_growth(amount_series),
                "volatility_20d": _volatility(series),
                "drawdown_60d": _drawdown(series),
            }
        )
    frame = pd.DataFrame(rows).set_index("symbol")
    frame["liquidity_score"] = _percentile(frame["amount_20d"])
    frame["amount_growth_score"] = _percentile(frame["amount_growth_20d"])
    frame["relative_1m_score"] = _percentile(frame["relative_1m"])
    frame["relative_3m_score"] = _percentile(frame["relative_3m"])
    frame["relative_6m_score"] = _percentile(frame["relative_6m"])
    frame["momentum_score"] = (
        frame["relative_1m_score"] * 0.20
        + frame["relative_3m_score"] * 0.35
        + frame["relative_6m_score"] * 0.20
        + frame["ma_score"] * 0.15
        + frame["amount_growth_score"] * 0.10
    )
    frame["risk_score"] = [
        _score_from_risk(row.volatility_20d, row.drawdown_60d, row.return_3m)
        for row in frame.itertuples()
    ]
    return frame, target_date


def _input_for_symbol(
    symbol: str,
    theme: str,
    etf_type: str,
    by_symbol: dict[str, RotationInputs],
    by_theme: dict[str, RotationInputs],
) -> RotationInputs:
    if symbol in by_symbol:
        return by_symbol[symbol]
    if theme in by_theme:
        item = by_theme[theme]
        if item.etf_type and item.etf_type != "其他":
            return item
        return RotationInputs(
            symbol=symbol,
            theme=theme,
            etf_type=etf_type,
            boom_status=item.boom_status,
            boom_score=item.boom_score,
            valuation_percentile=item.valuation_percentile,
            structure_score=item.structure_score,
            notes=item.notes,
        )
    return RotationInputs(symbol=symbol, theme=theme, etf_type=etf_type)


def _drivers(
    boom_score: float,
    momentum_score: float,
    valuation_score: float,
    liquidity_score: float,
) -> list[str]:
    output = []
    if boom_score >= 70:
        output.append("景气评分较高")
    if momentum_score >= 70:
        output.append("相对动量较强")
    if valuation_score >= 70:
        output.append("估值赔率较好")
    if liquidity_score >= 70:
        output.append("流动性较好")
    return output or ["优势不突出，适合作为观察对照"]


def _risk_notes(
    boom_score: float,
    momentum_score: float,
    valuation_percentile: float,
    liquidity_score: float,
    risk_score: float,
) -> list[str]:
    notes = []
    if valuation_percentile >= 80:
        notes.append("估值分位偏高，追高赔率不足。")
    if momentum_score >= 75 and boom_score < 55:
        notes.append("动量强但景气评分不足，可能偏资金炒作。")
    if liquidity_score < 30:
        notes.append("成交额分位偏低，流动性承载力需要验证。")
    if risk_score < 45:
        notes.append("波动或回撤压力偏高，仓位需控制。")
    return notes or ["未触发核心风险阈值，但仍需跟踪数据新鲜度和主题拥挤度。"]


def _state_and_action(
    boom_score: float,
    momentum_score: float,
    valuation_score: float,
    valuation_percentile: float,
    risk_score: float,
) -> tuple[str, str]:
    if valuation_percentile >= 90 and risk_score < 60:
        return "高估值 + 高拥挤", "控仓/回避追高"
    if boom_score >= 70 and momentum_score >= 70:
        return "景气上行 + 动量确认", "主线候选"
    if boom_score >= 70 and momentum_score < 60:
        return "景气上行 + 动量未确认", "左侧观察"
    if momentum_score >= 75 and boom_score < 55:
        return "动量强 + 景气弱", "谨慎观察"
    if valuation_score >= 70 and boom_score < 50:
        return "低估值 + 景气下行", "价值陷阱"
    if boom_score >= 55 and momentum_score >= 60:
        return "景气改善 + 动量改善", "重点跟踪"
    if momentum_score < 45 and boom_score < 55:
        return "景气/动量均弱", "暂不优先"
    return "中性震荡", "继续观察"


def build_rotation_report(
    *,
    top_n: int = 10,
    input_path: Path | None = None,
) -> RotationReport:
    daily = _clean_daily()
    metrics, target_date = _metric_frame(daily)
    if metrics.empty or target_date is None:
        return RotationReport(
            date=None,
            rankings=[],
            pools={},
            data_notes=["缺少可用 ETF 日线数据，无法生成行业主题轮动雷达。"],
        )

    basic_lookup = _basic_lookup()
    by_symbol, by_theme = _load_rotation_inputs(input_path)
    scores: list[RotationScore] = []
    for symbol, row in metrics.iterrows():
        basic = basic_lookup.get(symbol, {})
        name = str(basic.get("name") or symbol)
        theme = infer_etf_theme(name, basic.get("index_name"))
        etf_type = infer_etf_type(name, theme)
        manual = _input_for_symbol(symbol, theme, etf_type, by_symbol, by_theme)
        boom_score = _clip_score(manual.boom_score)
        valuation_percentile = _clip_score(manual.valuation_percentile)
        valuation_score = _clip_score(100 - valuation_percentile)
        structure_score = _clip_score(manual.structure_score, default=60.0)
        momentum_score = _clip_score(row["momentum_score"])
        liquidity_score = _clip_score(row["liquidity_score"])
        risk_score = _clip_score(row["risk_score"])
        total_score = (
            boom_score * 0.30
            + momentum_score * 0.25
            + valuation_score * 0.15
            + structure_score * 0.10
            + liquidity_score * 0.10
            + risk_score * 0.10
        )
        state, action = _state_and_action(
            boom_score,
            momentum_score,
            valuation_score,
            valuation_percentile,
            risk_score,
        )
        scores.append(
            RotationScore(
                symbol=symbol,
                name=name,
                theme=theme,
                etf_type=manual.etf_type or etf_type,
                date=target_date,
                total_score=round(float(total_score), 2),
                boom_score=round(boom_score, 2),
                momentum_score=round(momentum_score, 2),
                valuation_score=round(valuation_score, 2),
                structure_score=round(structure_score, 2),
                liquidity_score=round(liquidity_score, 2),
                risk_score=round(risk_score, 2),
                boom_status=manual.boom_status,
                valuation_percentile=round(valuation_percentile, 2),
                state=state,
                action=action,
                returns={
                    "1m": None if pd.isna(row["return_1m"]) else round(float(row["return_1m"]), 4),
                    "3m": None if pd.isna(row["return_3m"]) else round(float(row["return_3m"]), 4),
                    "6m": None if pd.isna(row["return_6m"]) else round(float(row["return_6m"]), 4),
                    "relative_3m": (
                        None
                        if pd.isna(row["relative_3m"])
                        else round(float(row["relative_3m"]), 4)
                    ),
                },
                risk_notes=_risk_notes(
                    boom_score,
                    momentum_score,
                    valuation_percentile,
                    liquidity_score,
                    risk_score,
                ),
                drivers=_drivers(boom_score, momentum_score, valuation_score, liquidity_score),
                input_notes=manual.notes,
            )
        )

    rankings = sorted(scores, key=lambda item: (-item.total_score, item.symbol))
    pools = {
        "core_candidates": [
            item for item in rankings if item.action in {"主线候选", "重点跟踪"}
        ][:top_n],
        "watchlist": [
            item for item in rankings if item.action in {"左侧观察", "谨慎观察", "继续观察"}
        ][:top_n],
        "avoid": [
            item
            for item in rankings
            if item.action in {"价值陷阱", "控仓/回避追高", "暂不优先"}
        ][:top_n],
    }
    data_notes = [
        "v0.1 使用日线价格、成交额、可选人工景气和估值输入生成行业主题 ETF 轮动雷达。",
        f"人工输入文件: {str(input_path or settings.rotation_input_path)}。",
        "景气和估值缺失时采用中性 50 分，不会假装自动理解行业基本面。",
    ]
    return RotationReport(
        date=target_date,
        rankings=rankings[: max(top_n, 1)],
        pools=pools,
        data_notes=data_notes,
    )
