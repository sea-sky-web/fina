from __future__ import annotations

from datetime import date

import pandas as pd

from app.core.config import settings
from app.factors.registry import FACTOR_REGISTRY
from app.models import (
    MarketRegimeSnapshot,
    ResearchSignal,
    SignalComponent,
    SignalExplanation,
)
from app.risk import MarketRegime, detect_market_regime
from app.services.evaluation_service import generate_factor_pool_report
from app.services.factor_service import _read_factors
from app.services.records import dataframe_records
from app.services.theme_classifier import infer_etf_theme
from app.storage.parquet_store import read_parquet
from app.synthesis import FALLBACK_SIGNAL_WEIGHTS, adjust_weights_for_regime, icir_weights

LIQUIDITY_FACTOR = "turnover_20d"
VOLATILITY_FACTOR = "volatility_30d"
DRAWDOWN_FACTOR = "max_drawdown_60d"


def _priority(score: float) -> str:
    if score >= 75:
        return "观察优先级高"
    if score >= 55:
        return "观察优先级中"
    return "观察优先级低"


def _format_percentile(value: float) -> str:
    return f"{value * 100:.0f}%"


def _load_basic_lookup() -> dict[str, dict[str, object]]:
    basic = read_parquet(settings.clean_dir / "etf_basic.parquet")
    if basic.empty:
        return {}
    keep = [column for column in ["symbol", "name", "index_name"] if column in basic.columns]
    basic = basic[keep].copy()
    return {record["symbol"]: record for record in dataframe_records(basic)}


def _read_signal_factors() -> pd.DataFrame:
    try:
        processed = _read_factors(processed=True)
    except Exception:
        processed = pd.DataFrame()
    if not processed.empty:
        return processed
    return _read_factors()


def _daily_for_regime() -> pd.DataFrame:
    daily = read_parquet(settings.clean_dir / "etf_daily.parquet")
    if daily.empty:
        return pd.DataFrame(columns=["symbol", "date", "close"])
    keep = [column for column in ["symbol", "date", "close"] if column in daily.columns]
    return daily[keep].copy()


def _regime_snapshot(regime: MarketRegime) -> MarketRegimeSnapshot:
    return MarketRegimeSnapshot(
        label=regime.label,
        label_zh=regime.label_zh,
        date=regime.date,
        target_exposure=regime.target_exposure,
        trend_score=regime.trend_score,
        volatility_annualized=regime.volatility_annualized,
        drawdown=regime.drawdown,
        source=regime.source,
        data_notes=regime.data_notes,
    )


def _target_factor_frame(signal_date: date | None) -> tuple[pd.DataFrame, date | None]:
    factors = _read_signal_factors()
    if factors.empty:
        return factors, None

    factors = factors.copy()
    factors["date"] = pd.to_datetime(factors["date"]).dt.date
    target_date = signal_date or factors["date"].max()
    return factors[factors["date"] == target_date].copy(), target_date


def _signal_weights() -> tuple[dict[str, float], str]:
    try:
        report = generate_factor_pool_report(horizons=[20], processed=True)
        weights = icir_weights(report.individual_reports, report.correlation_matrix)
    except Exception:
        return FALLBACK_SIGNAL_WEIGHTS.copy(), "使用固定研究权重；评估样本暂不足以动态加权。"

    if weights == FALLBACK_SIGNAL_WEIGHTS:
        return FALLBACK_SIGNAL_WEIGHTS.copy(), "使用固定研究权重；ICIR 筛选未产生稳定动态权重。"
    return weights, "因子权重基于历史 ICIR，并对高相关因子做了降权。"


def _component_from_row(row: pd.Series, weight: float, available_weight: float) -> SignalComponent:
    factor = FACTOR_REGISTRY[row["factor_name"]]
    contribution = (
        float(row["percentile"]) * weight / available_weight * 100
        if available_weight
        else 0.0
    )
    return SignalComponent(
        factor_name=factor.name,
        label=factor.label,
        category=factor.category,
        direction=factor.direction,
        value_format=factor.value_format,
        factor_value=float(row["factor_value"]),
        rank=int(row["rank"]),
        percentile=float(row["percentile"]),
        weight=weight,
        contribution=round(contribution, 2),
        interpretation=factor.interpretation,
    )


def _explain_signal(
    signal_date: date,
    score: float,
    components: list[SignalComponent],
    by_factor: dict[str, pd.Series],
    weight_note: str,
    regime: MarketRegime,
) -> SignalExplanation:
    positive_drivers = [
        (
            f"{item.label}处于{_format_percentile(item.percentile)}有利分位，"
            f"贡献 {item.contribution:.1f} 分。"
        )
        for item in sorted(
            components,
            key=lambda component: component.contribution,
            reverse=True,
        )[:3]
        if item.percentile >= 0.55
    ]
    if not positive_drivers:
        positive_drivers = ["当前没有特别突出的优势因子，适合作为对照样本继续观察。"]

    risk_notes: list[str] = []
    turnover = by_factor.get(LIQUIDITY_FACTOR)
    if turnover is not None and float(turnover["percentile"]) < 0.30:
        risk_notes.append("20日均成交额处于较低有利分位，流动性待验证。")
    volatility = by_factor.get(VOLATILITY_FACTOR)
    if volatility is not None and float(volatility["percentile"]) < 0.20:
        risk_notes.append("30日波动率处于较不利位置，短期波动风险偏高。")
    drawdown = by_factor.get(DRAWDOWN_FACTOR)
    if drawdown is not None and float(drawdown["percentile"]) < 0.20:
        risk_notes.append("60日最大回撤处于较不利位置，回撤风险偏高。")
    if regime.label == "risk_off":
        risk_notes.append("当前市场状态偏防御，信号分数会更重视低波动、低回撤和流动性稳定。")
    if not risk_notes:
        risk_notes.append("当前核心风险因子没有触发高风险阈值，但仍需结合数据新鲜度和主题波动观察。")

    validation_notes = [
        "继续观察趋势强度是否能维持在较高分位。",
        "确认成交额是否保持稳定，避免单日放量造成误判。",
    ]
    if score < 55:
        validation_notes.append("综合研究分偏低，优先作为低关注度样本跟踪。")

    return SignalExplanation(
        positive_drivers=positive_drivers,
        risk_notes=risk_notes,
        validation_notes=validation_notes,
        data_notes=[
            f"信号基于 {signal_date.isoformat()} 的本地清洗数据和因子结果。",
            weight_note,
            f"动态状态: {regime.label_zh}，建议风险暴露 {regime.target_exposure:.0%}。",
            "本页面仅用于历史研究和观察解释，不构成投资建议。",
        ],
    )


def _build_signal(
    symbol: str,
    frame: pd.DataFrame,
    signal_date: date,
    basic_lookup: dict[str, dict[str, object]],
    weights: dict[str, float],
    weight_note: str,
    regime: MarketRegime,
) -> ResearchSignal | None:
    rows = frame[frame["symbol"] == symbol]
    if rows.empty:
        return None

    by_factor = {row["factor_name"]: row for _, row in rows.iterrows()}
    available_weight = sum(weight for name, weight in weights.items() if name in by_factor)
    if available_weight <= 0:
        return None

    components = [
        _component_from_row(by_factor[name], weight, available_weight)
        for name, weight in weights.items()
        if name in by_factor
    ]
    research_score = round(sum(component.contribution for component in components), 2)
    basic = basic_lookup.get(symbol, {})
    name = str(basic.get("name") or symbol)
    theme = infer_etf_theme(name, basic.get("index_name"))
    updated_at = rows["updated_at"].dropna().max() if "updated_at" in rows.columns else None

    return ResearchSignal(
        symbol=symbol,
        name=name,
        theme=theme,
        date=signal_date,
        research_score=research_score,
        priority=_priority(research_score),
        components=components,
        explanation=_explain_signal(
            signal_date,
            research_score,
            components,
            by_factor,
            weight_note,
            regime,
        ),
        market_regime=_regime_snapshot(regime),
        target_exposure=regime.target_exposure,
        provider="local",
        updated_at=updated_at if pd.notna(updated_at) else None,
    )


def list_research_signals(
    signal_date: date | None = None,
    theme: str | None = None,
    limit: int = 100,
) -> list[ResearchSignal]:
    factors, target_date = _target_factor_frame(signal_date)
    if factors.empty or target_date is None:
        return []

    basic_lookup = _load_basic_lookup()
    base_weights, weight_note = _signal_weights()
    regime = detect_market_regime(_daily_for_regime(), target_date)
    weights, regime_note = adjust_weights_for_regime(base_weights, regime.label)
    weight_note = f"{weight_note} {regime_note}"
    symbols = sorted(factors["symbol"].dropna().unique())
    signals = [
        signal
        for symbol in symbols
        if (
            signal := _build_signal(
                symbol,
                factors,
                target_date,
                basic_lookup,
                weights,
                weight_note,
                regime,
            )
        )
        is not None
    ]
    if theme and theme != "全部":
        signals = [signal for signal in signals if signal.theme == theme]
    signals.sort(key=lambda item: (-item.research_score, item.symbol))
    return signals[:limit]


def get_research_signal(symbol: str, signal_date: date | None = None) -> ResearchSignal | None:
    factors, target_date = _target_factor_frame(signal_date)
    if factors.empty or target_date is None:
        return None
    basic_lookup = _load_basic_lookup()
    base_weights, weight_note = _signal_weights()
    regime = detect_market_regime(_daily_for_regime(), target_date)
    weights, regime_note = adjust_weights_for_regime(base_weights, regime.label)
    weight_note = f"{weight_note} {regime_note}"
    return _build_signal(symbol, factors, target_date, basic_lookup, weights, weight_note, regime)
