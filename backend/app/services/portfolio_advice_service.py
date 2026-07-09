from __future__ import annotations

import pandas as pd

from app.core.config import settings
from app.models import (
    MarketRegimeSnapshot,
    PortfolioAdviceItem,
    PortfolioAdviceReport,
    PortfolioAdviceRequest,
    PortfolioHoldingInput,
)
from app.risk import build_risk_adjusted_portfolio, detect_market_regime
from app.risk.regime import MarketRegime
from app.services.rotation_service import RotationScore, build_rotation_report
from app.storage.parquet_store import read_parquet

TARGET_ROTATION_ACTIONS = {"主线候选", "重点跟踪"}


def _clean_daily() -> pd.DataFrame:
    daily = read_parquet(settings.clean_dir / "etf_daily.parquet")
    if daily.empty or not {"symbol", "date", "close"}.issubset(daily.columns):
        return pd.DataFrame(columns=["symbol", "date", "close"])
    frame = daily[["symbol", "date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["symbol", "date", "close"]).sort_values(["symbol", "date"])


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


def _current_weights(holdings: list[PortfolioHoldingInput]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for holding in holdings:
        symbol = holding.symbol.strip().upper()
        if not symbol or holding.weight <= 0:
            continue
        weights[symbol] = weights.get(symbol, 0.0) + holding.weight
    return weights


def _format_pct(value: float) -> str:
    return f"{value:.1%}"


def _format_delta(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.1f}pct"


def _advice_action(current_weight: float, target_weight: float, min_trade_weight: float) -> str:
    delta = target_weight - current_weight
    if target_weight > 0 and current_weight <= 0:
        return "新增配置候选"
    if delta >= min_trade_weight:
        return "加仓候选"
    if delta <= -min_trade_weight:
        return "减仓候选"
    return "持有不变"


def _item_metadata(symbol: str, score: RotationScore | None) -> tuple[str, str, str]:
    if score is None:
        return symbol, "未入选", "未入选"
    return score.name, score.theme, score.etf_type


def _rationale(
    *,
    current_weight: float,
    target_weight: float,
    score: RotationScore | None,
    universe_limit: int,
) -> list[str]:
    rationale = [
        (
            f"当前权重 {_format_pct(current_weight)}，目标权重 "
            f"{_format_pct(target_weight)}，差值 {_format_delta(target_weight - current_weight)}。"
        )
    ]
    if target_weight > 0 and score is not None:
        rationale.append(
            f"进入目标组合: {score.state} / {score.action}，轮动总分 {score.total_score:.1f}。"
        )
    elif current_weight > 0 and score is not None:
        rationale.append(
            f"未进入本次目标组合: {score.state} / {score.action}，"
            f"轮动总分 {score.total_score:.1f}。"
        )
    elif current_weight > 0:
        rationale.append(
            f"未出现在当前行业/主题轮动雷达前 {universe_limit} 名，默认目标权重为 0。"
        )
    else:
        rationale.append("仅作为目标组合候选展示，当前组合未持有。")
    return rationale


def _build_item(
    *,
    symbol: str,
    score: RotationScore | None,
    current_weight: float,
    target_weight: float,
    min_trade_weight: float,
    universe_limit: int,
) -> PortfolioAdviceItem:
    name, theme, etf_type = _item_metadata(symbol, score)
    return PortfolioAdviceItem(
        symbol=symbol,
        name=name,
        theme=theme,
        etf_type=etf_type,
        current_weight=round(current_weight, 6),
        target_weight=round(target_weight, 6),
        delta_weight=round(target_weight - current_weight, 6),
        action=_advice_action(current_weight, target_weight, min_trade_weight),
        total_score=score.total_score if score is not None else None,
        state=score.state if score is not None else "未入选",
        rotation_action=score.action if score is not None else "未入选",
        rationale=_rationale(
            current_weight=current_weight,
            target_weight=target_weight,
            score=score,
            universe_limit=universe_limit,
        ),
        drivers=score.drivers if score is not None else [],
        risk_notes=(
            score.risk_notes
            if score is not None
            else ["缺少当前轮动雷达评分，需人工核对。"]
        ),
    )


def _estimated_turnover(
    current_weights: dict[str, float],
    target_weights: dict[str, float],
) -> float:
    if not current_weights:
        return float(sum(target_weights.values()))
    symbols = set(current_weights) | set(target_weights)
    return float(
        sum(
            abs(target_weights.get(symbol, 0.0) - current_weights.get(symbol, 0.0))
            for symbol in symbols
        )
        / 2
    )


def _sort_advice(items: list[PortfolioAdviceItem]) -> list[PortfolioAdviceItem]:
    priority = {
        "新增配置候选": 0,
        "加仓候选": 1,
        "减仓候选": 2,
        "持有不变": 3,
    }
    return sorted(
        items,
        key=lambda item: (
            priority.get(item.action, 9),
            -abs(item.delta_weight),
            item.symbol,
        ),
    )


def build_portfolio_advice(request: PortfolioAdviceRequest) -> PortfolioAdviceReport:
    current_weights = _current_weights(request.holdings)
    universe_limit = max(request.universe_limit, request.target_count, len(current_weights), 1)
    rotation = build_rotation_report(top_n=universe_limit)
    if rotation.date is None:
        return PortfolioAdviceReport(
            data_notes=[
                "缺少轮动雷达数据，无法生成持仓调整研究建议。",
                *rotation.data_notes,
            ],
        )

    scores_by_symbol = {item.symbol: item for item in rotation.rankings}
    target_candidates = [
        item
        for item in rotation.rankings
        if item.action in TARGET_ROTATION_ACTIONS
    ][: request.target_count]
    target_symbols = [item.symbol for item in target_candidates]

    daily = _clean_daily()
    regime = detect_market_regime(daily, rotation.date)
    themes = {item.symbol: item.theme for item in rotation.rankings}
    target_scores = {item.symbol: item.total_score for item in target_candidates}
    portfolio = build_risk_adjusted_portfolio(
        target_symbols,
        target_scores,
        daily,
        rotation.date,
        themes,
        regime,
    )

    ordered_symbols = [
        *target_symbols,
        *[symbol for symbol in current_weights if symbol not in target_symbols],
    ]
    advice = _sort_advice(
        [
            _build_item(
                symbol=symbol,
                score=scores_by_symbol.get(symbol),
                current_weight=current_weights.get(symbol, 0.0),
                target_weight=portfolio.weights.get(symbol, 0.0),
                min_trade_weight=request.min_trade_weight,
                universe_limit=universe_limit,
            )
            for symbol in ordered_symbols
        ]
    )

    data_notes = [
        "目标组合只从行业/主题轮动雷达中的主线候选和重点跟踪标的生成。",
        "动作标签表示相对当前持仓和目标权重的研究差异，不构成投资建议或下单指令。",
        f"最小调仓提示阈值为 {_format_pct(request.min_trade_weight)}。",
        *portfolio.notes,
        *rotation.data_notes,
    ]
    current_exposure = sum(current_weights.values())
    if current_exposure > 1.01:
        data_notes.append("当前输入权重合计超过 100%，请确认是否按组合权重小数填写。")
    if not current_weights:
        data_notes.append("未提供当前持仓；所有目标组合标的都会显示为新增配置候选。")

    return PortfolioAdviceReport(
        radar_date=rotation.date,
        current_exposure=round(current_exposure, 6),
        target_exposure=round(portfolio.realized_exposure, 6),
        cash_weight=round(portfolio.cash_weight, 6),
        estimated_turnover=round(_estimated_turnover(current_weights, portfolio.weights), 6),
        market_regime=_regime_snapshot(regime),
        advice=advice,
        target_symbols=target_symbols,
        data_notes=data_notes,
    )
