from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import sqrt

import pandas as pd

from app.core.config import settings
from app.models import (
    BacktestBenchmark,
    BacktestConfig,
    BacktestDataNote,
    BacktestEquityPoint,
    BacktestHolding,
    BacktestHoldingSnapshot,
    BacktestMetrics,
    BacktestResult,
    BacktestRiskSummary,
    BacktestValidationCheck,
    BacktestValidationSummary,
    MarketRegimeSnapshot,
)
from app.risk import (
    MarketRegime,
    RiskAdjustedPortfolio,
    build_risk_adjusted_portfolio,
    detect_market_regime,
)
from app.services.cache import FingerprintCache, clean_data_fingerprint
from app.services.evaluation_service import (
    calculate_factor_correlation_matrix,
    calculate_ic_stats,
    generate_factor_pool_report,
)
from app.services.factor_service import _read_factors
from app.services.rotation_service import build_rotation_report
from app.services.theme_classifier import infer_etf_theme
from app.storage.parquet_store import read_parquet
from app.synthesis import FALLBACK_SIGNAL_WEIGHTS, adjust_weights_for_regime, icir_weights

TRADING_DAYS_PER_YEAR = 252
DEFAULT_BACKTEST_UNIVERSE_SIZE = 100
DEFAULT_MIN_HISTORY_DAYS = 60
DEFAULT_ROTATION_CORE_TOP_N = 5
PRODUCTION_MIN_REBALANCES = 36
_BACKTEST_CACHE = FingerprintCache(max_items=32)
_WALK_FORWARD_CACHE = FingerprintCache(max_items=16)


@dataclass(frozen=True)
class _RebalanceSelection:
    rebalance_date: date
    effective_date: date | None
    symbols: list[str]
    scores: dict[str, float]
    factor_weights: dict[str, float] = field(default_factory=dict)
    regime: MarketRegime | None = None


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
    daily = daily[columns].copy()
    if "amount" not in daily.columns:
        daily["amount"] = pd.NA
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily["amount"] = pd.to_numeric(daily["amount"], errors="coerce")
    daily = daily.dropna(subset=["symbol", "date", "close"])
    return daily.sort_values(["symbol", "date"])


def _basic_lookup() -> dict[str, dict[str, object]]:
    basic = read_parquet(settings.clean_dir / "etf_basic.parquet")
    if basic.empty or "symbol" not in basic.columns:
        return {}
    keep = [column for column in ["symbol", "name", "index_name"] if column in basic.columns]
    basic = basic[keep].copy()
    return {
        str(record["symbol"]): record
        for record in basic.astype("object").where(pd.notna(basic), None).to_dict(orient="records")
    }


def _backtest_weights() -> tuple[dict[str, float], str]:
    try:
        report = generate_factor_pool_report(horizons=[20], processed=True)
        weights = icir_weights(report.individual_reports, report.correlation_matrix)
    except Exception:
        return FALLBACK_SIGNAL_WEIGHTS.copy(), "回测使用固定研究权重；评估样本暂不足。"

    if weights == FALLBACK_SIGNAL_WEIGHTS:
        return FALLBACK_SIGNAL_WEIGHTS.copy(), "回测使用固定研究权重；动态权重未通过质量门槛。"
    return weights, "回测研究分使用处理后因子和基于全样本 ICIR 的动态权重。"


def _score_frame(factors: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    if factors.empty:
        return pd.DataFrame(columns=["date", "symbol", "research_score"])
    frame = factors[factors["factor_name"].isin(weights)].copy()
    if frame.empty:
        return pd.DataFrame(columns=["date", "symbol", "research_score"])
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame["percentile"] = pd.to_numeric(frame["percentile"], errors="coerce")
    frame = frame.dropna(subset=["symbol", "date", "factor_name", "percentile"])
    frame["weight"] = frame["factor_name"].map(weights)
    frame["weighted_percentile"] = frame["percentile"] * frame["weight"]
    grouped = frame.groupby(["date", "symbol"], as_index=False).agg(
        weighted_percentile=("weighted_percentile", "sum"),
        available_weight=("weight", "sum"),
    )
    grouped = grouped[grouped["available_weight"] > 0].copy()
    grouped["research_score"] = (
        grouped["weighted_percentile"] / grouped["available_weight"] * 100
    )
    return grouped[["date", "symbol", "research_score"]]


def _point_in_time_universe(
    target_date: date,
    daily: pd.DataFrame,
    *,
    universe_size: int = DEFAULT_BACKTEST_UNIVERSE_SIZE,
    min_history_days: int = DEFAULT_MIN_HISTORY_DAYS,
) -> set[str]:
    historical = daily[daily["date"] <= target_date].copy()
    if historical.empty:
        return set()

    coverage = historical.groupby("symbol")["date"].nunique()
    eligible_symbols = set(coverage[coverage >= min_history_days].index)
    if not eligible_symbols:
        return set()

    historical = historical[historical["symbol"].isin(eligible_symbols)]
    if historical["amount"].notna().any():
        liquidity_rows = []
        for symbol, group in historical.groupby("symbol"):
            recent = group.sort_values("date").tail(20)
            liquidity_rows.append(
                {
                    "symbol": symbol,
                    "liquidity": recent["amount"].mean(skipna=True),
                }
            )
        liquidity = pd.DataFrame(liquidity_rows).dropna(subset=["liquidity"])
        if not liquidity.empty:
            return set(
                liquidity.sort_values(["liquidity", "symbol"], ascending=[False, True])
                .head(universe_size)["symbol"]
            )

    return set(sorted(eligible_symbols)[:universe_size])


def _month_end_signal_dates(scores: pd.DataFrame) -> list[date]:
    if scores.empty:
        return []
    by_date = scores[["date"]].drop_duplicates().copy()
    by_date["month"] = by_date["date"].map(lambda value: (value.year, value.month))
    return list(by_date.groupby("month")["date"].max().sort_values())


def _next_trading_date(trading_dates: list[date], rebalance_date: date) -> date | None:
    for trading_date in trading_dates:
        if trading_date > rebalance_date:
            return trading_date
    return None


def _select_rebalances(
    scores: pd.DataFrame,
    daily: pd.DataFrame,
    trading_dates: list[date],
    top_n: int,
) -> list[_RebalanceSelection]:
    selections: list[_RebalanceSelection] = []
    for rebalance_date in _month_end_signal_dates(scores):
        universe = _point_in_time_universe(rebalance_date, daily)
        if not universe:
            continue
        current = scores[scores["date"] == rebalance_date].copy()
        current = current[current["symbol"].isin(universe)]
        current = current.sort_values(
            ["research_score", "symbol"],
            ascending=[False, True],
        ).head(top_n)
        if current.empty:
            continue
        selections.append(
            _RebalanceSelection(
                rebalance_date=rebalance_date,
                effective_date=_next_trading_date(trading_dates, rebalance_date),
                symbols=list(current["symbol"]),
                scores=dict(zip(current["symbol"], current["research_score"], strict=False)),
            )
        )
    return selections


def _select_dynamic_rebalances(
    factors: pd.DataFrame,
    daily: pd.DataFrame,
    trading_dates: list[date],
    top_n: int,
    base_weights: dict[str, float],
    benchmark: str,
) -> list[_RebalanceSelection]:
    selections: list[_RebalanceSelection] = []
    if factors.empty or not base_weights:
        return selections

    factor_dates = factors[factors["factor_name"].isin(base_weights)][["date"]].drop_duplicates()
    for rebalance_date in _month_end_signal_dates(factor_dates):
        universe = _point_in_time_universe(rebalance_date, daily)
        if not universe:
            continue
        regime = detect_market_regime(daily, rebalance_date, benchmark=benchmark)
        factor_weights, _ = adjust_weights_for_regime(base_weights, regime.label)
        current_factors = factors[factors["date"] == rebalance_date].copy()
        current = _score_frame(current_factors, factor_weights)
        current = current[current["symbol"].isin(universe)]
        current = current.sort_values(
            ["research_score", "symbol"],
            ascending=[False, True],
        ).head(top_n)
        if current.empty:
            continue
        selections.append(
            _RebalanceSelection(
                rebalance_date=rebalance_date,
                effective_date=_next_trading_date(trading_dates, rebalance_date),
                symbols=list(current["symbol"]),
                scores=dict(zip(current["symbol"], current["research_score"], strict=False)),
                factor_weights=factor_weights,
                regime=regime,
            )
        )
    return selections


def _metrics_from_returns(
    returns: pd.Series,
    equity: pd.Series,
    average_turnover: float,
    count: int,
) -> BacktestMetrics:
    clean_returns = pd.to_numeric(returns, errors="coerce").dropna()
    clean_equity = pd.to_numeric(equity, errors="coerce").dropna()
    if clean_equity.empty:
        return BacktestMetrics(average_turnover=average_turnover, rebalance_count=count)

    cumulative_return = float(clean_equity.iloc[-1] - 1)
    periods = max(len(clean_returns), 1)
    annualized_return = float(clean_equity.iloc[-1] ** (TRADING_DAYS_PER_YEAR / periods) - 1)
    annualized_volatility = float(clean_returns.std(ddof=0) * sqrt(TRADING_DAYS_PER_YEAR))
    running_max = clean_equity.cummax()
    max_drawdown = float((clean_equity / running_max - 1).min())
    sharpe_like = (
        annualized_return / annualized_volatility
        if annualized_volatility and annualized_volatility > 0
        else None
    )
    win_rate = float((clean_returns > 0).mean()) if not clean_returns.empty else None
    return BacktestMetrics(
        cumulative_return=cumulative_return,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        max_drawdown=max_drawdown,
        sharpe_like=sharpe_like,
        win_rate_daily=win_rate,
        average_turnover=average_turnover,
        rebalance_count=count,
        final_equity=float(clean_equity.iloc[-1]),
    )


def _equity_points(returns: pd.Series) -> tuple[list[BacktestEquityPoint], pd.Series]:
    clean = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    equity = (1 + clean).cumprod()
    points = [
        BacktestEquityPoint(date=index, equity=float(value), daily_return=float(clean.loc[index]))
        for index, value in equity.items()
    ]
    return points, equity


def _benchmark_from_returns(
    key: str,
    label: str,
    returns: pd.Series,
    symbol: str | None = None,
) -> BacktestBenchmark:
    points, equity = _equity_points(returns)
    return BacktestBenchmark(
        key=key,
        label=label,
        symbol=symbol,
        metrics=_metrics_from_returns(returns, equity, 0.0, 0),
        equity_curve=points,
    )


def _holding_snapshot(
    selection: _RebalanceSelection,
    lookup: dict[str, dict[str, object]],
    portfolio: RiskAdjustedPortfolio,
    turnover: float,
    cost: float,
) -> BacktestHoldingSnapshot:
    holdings: list[BacktestHolding] = []
    for symbol in selection.symbols:
        basic = lookup.get(symbol, {})
        name = str(basic.get("name") or symbol)
        holdings.append(
            BacktestHolding(
                symbol=symbol,
                name=name,
                theme=infer_etf_theme(name, basic.get("index_name")),
                research_score=round(selection.scores.get(symbol, 0.0), 2),
                weight=portfolio.weights.get(symbol, 0.0),
            )
        )
    return BacktestHoldingSnapshot(
        rebalance_date=selection.rebalance_date,
        effective_date=selection.effective_date,
        holdings=holdings,
        turnover=turnover,
        cost=cost,
        regime=_regime_snapshot(selection.regime) if selection.regime is not None else None,
        target_exposure=portfolio.target_exposure,
        realized_exposure=portfolio.realized_exposure,
        cash_weight=portfolio.cash_weight,
        risk_notes=portfolio.notes,
    )


def _turnover(
    old_weights: dict[str, float],
    new_symbols: list[str],
) -> tuple[float, dict[str, float]]:
    if not new_symbols:
        return 0.0, {}
    new_weight = 1 / len(new_symbols)
    new_weights = {symbol: new_weight for symbol in new_symbols}
    if not old_weights:
        return 1.0, new_weights
    symbols = set(old_weights) | set(new_weights)
    turnover = (
        sum(
            abs(new_weights.get(symbol, 0.0) - old_weights.get(symbol, 0.0))
            for symbol in symbols
        )
        / 2
    )
    return float(turnover), new_weights


def _weight_turnover(
    old_weights: dict[str, float],
    new_weights: dict[str, float],
) -> tuple[float, dict[str, float]]:
    if not old_weights:
        return float(sum(new_weights.values())), new_weights
    symbols = set(old_weights) | set(new_weights)
    turnover = (
        sum(
            abs(new_weights.get(symbol, 0.0) - old_weights.get(symbol, 0.0))
            for symbol in symbols
        )
        / 2
    )
    return float(turnover), new_weights


def _regime_snapshot(regime: MarketRegime | None) -> MarketRegimeSnapshot | None:
    if regime is None:
        return None
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


def _themes_for_symbols(
    symbols: list[str],
    lookup: dict[str, dict[str, object]],
) -> dict[str, str]:
    themes: dict[str, str] = {}
    for symbol in symbols:
        basic = lookup.get(symbol, {})
        name = str(basic.get("name") or symbol)
        themes[symbol] = infer_etf_theme(name, basic.get("index_name"))
    return themes


def _weighted_period_returns(
    returns: pd.DataFrame,
    weights: dict[str, float],
) -> pd.Series:
    if returns.empty or not weights:
        return pd.Series(0.0, index=returns.index)
    columns = [symbol for symbol in weights if symbol in returns.columns]
    if not columns:
        return pd.Series(0.0, index=returns.index)
    weight_series = pd.Series({symbol: weights[symbol] for symbol in columns})
    return returns[columns].fillna(0.0).mul(weight_series, axis=1).sum(axis=1)


def _risk_summary(snapshots: list[BacktestHoldingSnapshot]) -> BacktestRiskSummary:
    if not snapshots:
        return BacktestRiskSummary()
    target_values = pd.Series([snapshot.target_exposure for snapshot in snapshots], dtype="float64")
    realized_values = pd.Series(
        [snapshot.realized_exposure for snapshot in snapshots],
        dtype="float64",
    )
    cash_values = pd.Series([snapshot.cash_weight for snapshot in snapshots], dtype="float64")
    risk_off_count = sum(
        1
        for snapshot in snapshots
        if snapshot.regime is not None and snapshot.regime.label == "risk_off"
    )
    constrained_count = sum(
        1
        for snapshot in snapshots
        if snapshot.realized_exposure < snapshot.target_exposure - 0.01
        or snapshot.cash_weight > max(0.01, 1 - snapshot.target_exposure + 0.01)
    )
    return BacktestRiskSummary(
        average_target_exposure=float(target_values.mean()),
        average_realized_exposure=float(realized_values.mean()),
        average_cash_weight=float(cash_values.mean()),
        risk_off_rebalance_count=risk_off_count,
        constrained_rebalance_count=constrained_count,
        data_notes=[
            "风险控制按调仓日点位数据执行，包含市场状态暴露、单只权重、主题集中度和高相关簇约束。",
            "风险约束压降后的未使用权重按现金/低风险仓位处理。",
        ],
    )


def _benchmark_metrics(
    benchmarks: list[BacktestBenchmark],
    *,
    key: str | None = None,
    symbol: str | None = None,
) -> BacktestMetrics | None:
    for benchmark in benchmarks:
        if key is not None and benchmark.key == key:
            return benchmark.metrics
        if symbol is not None and benchmark.symbol == symbol:
            return benchmark.metrics
    return None


def _greater(value: float | None, threshold: float | None) -> bool:
    return value is not None and threshold is not None and value > threshold


def _not_worse_drawdown(value: float | None, threshold: float | None) -> bool:
    return value is not None and threshold is not None and value >= threshold


def _validation_summary(
    *,
    metrics: BacktestMetrics,
    benchmarks: list[BacktestBenchmark],
    benchmark: str,
    rebalance_count: int,
    has_oos_validation: bool = False,
) -> BacktestValidationSummary:
    symbol_metrics = _benchmark_metrics(benchmarks, symbol=benchmark)
    universe_metrics = _benchmark_metrics(benchmarks, key="universe_equal_weight")
    benchmark_return = (
        symbol_metrics.cumulative_return if symbol_metrics is not None else None
    )
    universe_return = (
        universe_metrics.cumulative_return if universe_metrics is not None else None
    )
    benchmark_drawdown = symbol_metrics.max_drawdown if symbol_metrics is not None else None

    checks = [
        BacktestValidationCheck(
            key="beat_symbol_benchmark",
            label=f"扣成本后跑赢 {benchmark}",
            passed=_greater(metrics.cumulative_return, benchmark_return),
            value=metrics.cumulative_return,
            threshold=benchmark_return,
            severity="error",
            message="策略累计收益必须高于指定基准，否则不能称为回测跑赢。",
        ),
        BacktestValidationCheck(
            key="beat_universe_equal_weight",
            label="扣成本后跑赢 ETF 等权池",
            passed=_greater(metrics.cumulative_return, universe_return),
            value=metrics.cumulative_return,
            threshold=universe_return,
            severity="error",
            message="策略还需要跑赢同数据池的朴素等权基准，避免只是在吃 ETF 池 beta。",
        ),
        BacktestValidationCheck(
            key="positive_risk_adjusted_return",
            label="风险调整收益为正",
            passed=metrics.sharpe_like is not None and metrics.sharpe_like > 0,
            value=metrics.sharpe_like,
            threshold=0,
            severity="error",
            message="Sharpe-like 必须为正，负值不能作为生产研究策略。",
        ),
        BacktestValidationCheck(
            key="drawdown_not_worse_than_benchmark",
            label="最大回撤不差于基准",
            passed=_not_worse_drawdown(metrics.max_drawdown, benchmark_drawdown),
            value=metrics.max_drawdown,
            threshold=benchmark_drawdown,
            severity="warning",
            message="若收益来自更深回撤，只能算研究候选，不能直接生产批准。",
        ),
        BacktestValidationCheck(
            key="minimum_rebalances",
            label="调仓样本达到生产门槛",
            passed=rebalance_count >= PRODUCTION_MIN_REBALANCES,
            value=rebalance_count,
            threshold=PRODUCTION_MIN_REBALANCES,
            severity="warning",
            message="生产策略至少需要 36 次月度调仓，当前样本不足时只能算研究验证。",
        ),
        BacktestValidationCheck(
            key="walk_forward_oos",
            label="已通过样本外 walk-forward",
            passed=has_oos_validation,
            value="available" if has_oos_validation else "missing",
            threshold="available",
            severity="warning",
            message="生产批准必须补充样本外验证，避免回测过拟合。",
        ),
    ]
    hard_fail = any(not item.passed and item.severity == "error" for item in checks)
    production_pass = all(item.passed for item in checks)
    if production_pass:
        status = "production_pass"
        status_zh = "生产通过"
        conclusion = "扣成本后跑赢主要基准，并满足生产样本和样本外验证门槛。"
    elif hard_fail:
        status = "fail"
        status_zh = "验证失败"
        conclusion = "核心收益或风险调整收益未过关，不能作为有效策略。"
    else:
        status = "research_pass"
        status_zh = "研究通过，未生产批准"
        conclusion = (
            "扣成本后历史回测跑赢核心基准，但样本长度、回撤或样本外验证仍未满足生产门槛。"
        )

    return BacktestValidationSummary(
        status=status,
        status_zh=status_zh,
        benchmark_symbol=benchmark,
        benchmark_cumulative_return=benchmark_return,
        universe_cumulative_return=universe_return,
        excess_return_vs_benchmark=(
            None
            if metrics.cumulative_return is None or benchmark_return is None
            else metrics.cumulative_return - benchmark_return
        ),
        excess_return_vs_universe=(
            None
            if metrics.cumulative_return is None or universe_return is None
            else metrics.cumulative_return - universe_return
        ),
        checks=checks,
        conclusion=conclusion,
    )


def _backtest_cache_key(
    start: date | None,
    end: date | None,
    top_n: int,
    rebalance: str,
    cost_bps: float,
    benchmark: str,
) -> tuple[object, ...]:
    return (
        "research_signal_backtest",
        start,
        end,
        top_n,
        rebalance,
        cost_bps,
        benchmark,
        clean_data_fingerprint(
            ["etf_daily.parquet", "etf_basic.parquet", "factors_processed.parquet"]
        ),
    )


def run_research_signal_backtest(
    start: date | None = None,
    end: date | None = None,
    top_n: int = 10,
    rebalance: str = "monthly",
    cost_bps: float = 5.0,
    benchmark: str = "510300.SH",
) -> BacktestResult:
    cache_key = _backtest_cache_key(start, end, top_n, rebalance, cost_bps, benchmark)
    return _BACKTEST_CACHE.get_or_create(
        cache_key,
        lambda: _run_research_signal_backtest_uncached(
            start=start,
            end=end,
            top_n=top_n,
            rebalance=rebalance,
            cost_bps=cost_bps,
            benchmark=benchmark,
        ),
    )


def _run_research_signal_backtest_uncached(
    start: date | None = None,
    end: date | None = None,
    top_n: int = 10,
    rebalance: str = "monthly",
    cost_bps: float = 5.0,
    benchmark: str = "510300.SH",
) -> BacktestResult:
    config = BacktestConfig(
        start=start,
        end=end,
        top_n=top_n,
        rebalance=rebalance,
        cost_bps=cost_bps,
        benchmark=benchmark,
    )
    notes = [
        BacktestDataNote(message="回测结果仅用于历史研究和规则验证，不构成投资建议。"),
        BacktestDataNote(message="当前Top100 ETF池按现有本地数据构建，可能存在历史样本选择偏差。"),
    ]
    if rebalance != "monthly":
        notes.append(
            BacktestDataNote(
                severity="warning",
                message="第一版仅支持月度调仓，已按 monthly 处理。",
            )
        )

    daily = _clean_daily()
    factors = _read_factors(processed=True)
    if daily.empty or factors.empty:
        notes.append(
            BacktestDataNote(
                severity="warning",
                message="缺少日线或处理后因子数据，请先重建因子后再运行策略验证。",
            )
        )
        return BacktestResult(config=config, metrics=BacktestMetrics(), data_notes=notes)

    factors = factors.copy()
    factors["date"] = pd.to_datetime(factors["date"]).dt.date
    weights, weight_note = _backtest_weights()
    if not weights:
        notes.append(BacktestDataNote(severity="warning", message="缺少综合研究分历史样本。"))
        return BacktestResult(config=config, metrics=BacktestMetrics(), data_notes=notes)
    notes.append(BacktestDataNote(message=weight_note))
    notes.append(
        BacktestDataNote(
            message="每个调仓日按市场状态动态倾斜因子权重，并用风险约束后的权重计算组合收益。"
        )
    )

    daily = daily.copy()
    if start is not None:
        daily = daily[daily["date"] >= start]
        factors = factors[factors["date"] >= start]
    if end is not None:
        daily = daily[daily["date"] <= end]
        factors = factors[factors["date"] <= end]

    prices = daily.pivot_table(
        index="date",
        columns="symbol",
        values="close",
        aggfunc="last",
    ).sort_index()
    returns = prices.pct_change(fill_method=None)
    trading_dates = list(prices.index)
    selections = _select_dynamic_rebalances(
        factors,
        daily,
        trading_dates,
        top_n,
        weights,
        benchmark,
    )
    selections = [selection for selection in selections if selection.effective_date is not None]
    if len(selections) < 2:
        notes.append(
            BacktestDataNote(
                severity="warning",
                message="可用调仓样本不足，暂不生成有效性结论。",
            )
        )
        return BacktestResult(config=config, metrics=BacktestMetrics(), data_notes=notes)

    strategy_returns = pd.Series(0.0, index=returns.index)
    cost_rate = cost_bps / 10000
    lookup = _basic_lookup()
    snapshots: list[BacktestHoldingSnapshot] = []
    old_weights: dict[str, float] = {}
    turnovers: list[float] = []

    for index, selection in enumerate(selections):
        assert selection.effective_date is not None
        next_effective = (
            selections[index + 1].effective_date
            if index + 1 < len(selections)
            else None
        )
        period_mask = returns.index >= selection.effective_date
        if next_effective is not None:
            period_mask &= returns.index < next_effective
        themes = _themes_for_symbols(selection.symbols, lookup)
        regime = selection.regime or detect_market_regime(
            daily,
            selection.rebalance_date,
            benchmark=benchmark,
        )
        portfolio = build_risk_adjusted_portfolio(
            selection.symbols,
            selection.scores,
            daily,
            selection.rebalance_date,
            themes,
            regime,
        )
        selected_returns = returns.loc[period_mask, list(portfolio.weights)]
        selected_returns = selected_returns.dropna(axis=1, how="all")
        period_returns = _weighted_period_returns(selected_returns, portfolio.weights)
        turnover, old_weights = _weight_turnover(old_weights, portfolio.weights)
        cost = turnover * cost_rate
        if not period_returns.empty:
            period_returns.iloc[0] = period_returns.iloc[0] - cost
            strategy_returns.loc[period_returns.index] = period_returns
        turnovers.append(turnover)
        snapshots.append(_holding_snapshot(selection, lookup, portfolio, turnover, cost))

    first_effective = selections[0].effective_date
    assert first_effective is not None
    strategy_returns = strategy_returns[strategy_returns.index >= first_effective]
    equity_curve, equity = _equity_points(strategy_returns)
    average_turnover = float(pd.Series(turnovers).mean()) if turnovers else 0.0
    metrics = _metrics_from_returns(strategy_returns, equity, average_turnover, len(snapshots))

    benchmarks: list[BacktestBenchmark] = []
    aligned_returns = returns.loc[strategy_returns.index]
    if benchmark in aligned_returns.columns:
        benchmarks.append(
            _benchmark_from_returns(
                key="symbol",
                label=f"{benchmark} 基准",
                symbol=benchmark,
                returns=aligned_returns[benchmark].fillna(0.0),
            )
        )
    else:
        notes.append(
            BacktestDataNote(
                severity="warning",
                message=f"本地数据缺少 {benchmark}，已跳过该基准。",
            )
        )
    universe_returns = aligned_returns.mean(axis=1, skipna=True).fillna(0.0)
    benchmarks.append(
        _benchmark_from_returns(
            key="universe_equal_weight",
            label="ETF池等权基准",
            returns=universe_returns,
        )
    )
    notes.append(
        BacktestDataNote(
            message=(
                "信号在调仓日收盘后读取，组合收益从下一交易日开始计算，"
                f"单边成本 {cost_bps:g}bp。"
            )
        )
    )
    notes.append(
        BacktestDataNote(
            message=(
                "每个调仓日使用当时可见历史数据构建流动性 ETF 池；"
                "基础因子权重来自全样本评估，调仓日再按市场状态做动态倾斜。"
            )
        )
    )

    return BacktestResult(
        config=config,
        metrics=metrics,
        equity_curve=equity_curve,
        benchmarks=benchmarks,
        holdings=snapshots,
        risk_summary=_risk_summary(snapshots),
        validation=_validation_summary(
            metrics=metrics,
            benchmarks=benchmarks,
            benchmark=benchmark,
            rebalance_count=len(snapshots),
        ),
        data_notes=notes,
    )


def _rotation_core_cache_key(
    start: date | None,
    end: date | None,
    top_n: int,
    rebalance: str,
    cost_bps: float,
    benchmark: str,
    min_liquidity_score: float,
    min_risk_score: float,
    risk_managed: bool,
) -> tuple[object, ...]:
    return (
        "rotation_core_backtest",
        start,
        end,
        top_n,
        rebalance,
        cost_bps,
        benchmark,
        min_liquidity_score,
        min_risk_score,
        risk_managed,
        clean_data_fingerprint(["etf_daily.parquet", "etf_basic.parquet"]),
    )


def run_rotation_core_backtest(
    start: date | None = None,
    end: date | None = None,
    top_n: int = DEFAULT_ROTATION_CORE_TOP_N,
    rebalance: str = "monthly",
    cost_bps: float = 5.0,
    benchmark: str = "510300.SH",
    min_liquidity_score: float = 0.0,
    min_risk_score: float = 60.0,
    risk_managed: bool = True,
) -> BacktestResult:
    cache_key = _rotation_core_cache_key(
        start,
        end,
        top_n,
        rebalance,
        cost_bps,
        benchmark,
        min_liquidity_score,
        min_risk_score,
        risk_managed,
    )
    return _BACKTEST_CACHE.get_or_create(
        cache_key,
        lambda: _run_rotation_core_backtest_uncached(
            start=start,
            end=end,
            top_n=top_n,
            rebalance=rebalance,
            cost_bps=cost_bps,
            benchmark=benchmark,
            min_liquidity_score=min_liquidity_score,
            min_risk_score=min_risk_score,
            risk_managed=risk_managed,
        ),
    )


def _rotation_core_selections(
    daily: pd.DataFrame,
    trading_dates: list[date],
    *,
    start: date | None,
    end: date | None,
    top_n: int,
    min_liquidity_score: float,
    min_risk_score: float,
) -> list[_RebalanceSelection]:
    dates = pd.DataFrame({"date": trading_dates})
    selections: list[_RebalanceSelection] = []
    for signal_date in _month_end_signal_dates(dates):
        if start is not None and signal_date < start:
            continue
        if end is not None and signal_date > end:
            continue
        rotation = build_rotation_report(
            top_n=max(top_n, 1),
            target_date=signal_date,
            use_manual_inputs=False,
        )
        if rotation.date is None:
            continue
        effective_date = _next_trading_date(trading_dates, rotation.date)
        if effective_date is None or (end is not None and effective_date > end):
            continue
        candidates = [
            item
            for item in rotation.pools.get("core_candidates", [])
            if item.liquidity_score >= min_liquidity_score
            and item.risk_score >= min_risk_score
        ]
        candidates = sorted(candidates, key=lambda item: (-item.total_score, item.symbol))[:top_n]
        selections.append(
            _RebalanceSelection(
                rebalance_date=rotation.date,
                effective_date=effective_date,
                symbols=[item.symbol for item in candidates],
                scores={item.symbol: item.total_score for item in candidates},
            )
        )
    return selections


def _run_rotation_core_backtest_uncached(
    start: date | None = None,
    end: date | None = None,
    top_n: int = DEFAULT_ROTATION_CORE_TOP_N,
    rebalance: str = "monthly",
    cost_bps: float = 5.0,
    benchmark: str = "510300.SH",
    min_liquidity_score: float = 0.0,
    min_risk_score: float = 60.0,
    risk_managed: bool = True,
) -> BacktestResult:
    config = BacktestConfig(
        strategy="rotation_core_risk_managed" if risk_managed else "rotation_core",
        risk_managed=risk_managed,
        start=start,
        end=end,
        top_n=top_n,
        rebalance=rebalance,
        cost_bps=cost_bps,
        benchmark=benchmark,
        pool="core_candidates",
        min_liquidity_score=min_liquidity_score,
        min_risk_score=min_risk_score,
    )
    notes = [
        BacktestDataNote(message="回测结果仅用于历史研究和规则验证，不构成投资建议。"),
        BacktestDataNote(
            message=(
                "轮动核心池策略只使用历史月末当时可见的行业/主题轮动雷达，"
                "禁用人工 CSV 输入，并选择 core_candidates 等权配置。"
            )
        ),
        BacktestDataNote(
            message=(
                "参数来源：1/3/6 月相对强弱和均线确认来自公开动量/趋势文献；"
                "交易成本按单边 bp 扣减，生产版仍需补动态价差和冲击成本。"
            )
        ),
    ]
    if risk_managed:
        notes.append(
            BacktestDataNote(
                message=(
                    "风险管理版默认要求 risk_score >= 60，并使用市场状态、单只权重、"
                    "主题集中度和高相关簇约束；无合格标的的调仓期转为现金。"
                )
            )
        )
    if rebalance != "monthly":
        notes.append(
            BacktestDataNote(
                severity="warning",
                message="第一版轮动核心池回测仅支持月度调仓，已按 monthly 处理。",
            )
        )

    daily = _clean_daily()
    if daily.empty:
        notes.append(
            BacktestDataNote(
                severity="warning",
                message="缺少 clean ETF 日线数据，无法运行轮动核心池回测。",
            )
        )
        return BacktestResult(config=config, metrics=BacktestMetrics(), data_notes=notes)

    prices = daily.pivot_table(
        index="date",
        columns="symbol",
        values="close",
        aggfunc="last",
    ).sort_index()
    returns = prices.pct_change(fill_method=None)
    trading_dates = list(prices.index)
    selections = _rotation_core_selections(
        daily,
        trading_dates,
        start=start,
        end=end,
        top_n=top_n,
        min_liquidity_score=min_liquidity_score,
        min_risk_score=min_risk_score,
    )
    selections = [selection for selection in selections if selection.effective_date is not None]
    if len(selections) < 2:
        notes.append(
            BacktestDataNote(
                severity="warning",
                message="可用轮动核心池调仓样本不足，暂不生成有效性结论。",
            )
        )
        return BacktestResult(config=config, metrics=BacktestMetrics(), data_notes=notes)

    strategy_returns = pd.Series(0.0, index=returns.index)
    cost_rate = cost_bps / 10000
    lookup = _basic_lookup()
    snapshots: list[BacktestHoldingSnapshot] = []
    old_weights: dict[str, float] = {}
    turnovers: list[float] = []

    for index, selection in enumerate(selections):
        assert selection.effective_date is not None
        next_effective = (
            selections[index + 1].effective_date
            if index + 1 < len(selections)
            else None
        )
        period_mask = returns.index >= selection.effective_date
        if next_effective is not None:
            period_mask &= returns.index < next_effective
        if end is not None:
            period_mask &= returns.index <= end
        regime = detect_market_regime(
            daily,
            selection.rebalance_date,
            benchmark=benchmark,
        )
        if risk_managed:
            themes = _themes_for_symbols(selection.symbols, lookup)
            portfolio = build_risk_adjusted_portfolio(
                selection.symbols,
                selection.scores,
                daily,
                selection.rebalance_date,
                themes,
                regime,
            )
            weights = portfolio.weights
        elif selection.symbols:
            weight = 1 / len(selection.symbols)
            weights = {symbol: weight for symbol in selection.symbols}
            portfolio = RiskAdjustedPortfolio(
                weights=weights,
                cash_weight=0.0,
                target_exposure=1.0,
                realized_exposure=1.0,
                notes=[
                    "轮动核心池回测采用等权满仓，用于检验信号分层；实盘组合层另行施加风险约束。"
                ],
            )
        else:
            weights = {}
            portfolio = RiskAdjustedPortfolio(
                weights={},
                cash_weight=1.0,
                target_exposure=1.0,
                realized_exposure=0.0,
                notes=["本期无合格核心池标的，组合转为现金/低风险仓位。"],
            )
        selected_returns = returns.loc[period_mask, list(weights)]
        selected_returns = selected_returns.dropna(axis=1, how="all")
        period_returns = _weighted_period_returns(selected_returns, weights)
        turnover, old_weights = _weight_turnover(old_weights, weights)
        cost = turnover * cost_rate
        if not period_returns.empty:
            period_returns.iloc[0] = period_returns.iloc[0] - cost
            strategy_returns.loc[period_returns.index] = period_returns
        turnovers.append(turnover)
        snapshot_selection = _RebalanceSelection(
            rebalance_date=selection.rebalance_date,
            effective_date=selection.effective_date,
            symbols=selection.symbols,
            scores=selection.scores,
            regime=regime if risk_managed else None,
        )
        snapshots.append(_holding_snapshot(snapshot_selection, lookup, portfolio, turnover, cost))

    first_effective = selections[0].effective_date
    assert first_effective is not None
    strategy_returns = strategy_returns[strategy_returns.index >= first_effective]
    if end is not None:
        strategy_returns = strategy_returns[strategy_returns.index <= end]
    equity_curve, equity = _equity_points(strategy_returns)
    average_turnover = float(pd.Series(turnovers).mean()) if turnovers else 0.0
    metrics = _metrics_from_returns(strategy_returns, equity, average_turnover, len(snapshots))

    benchmarks: list[BacktestBenchmark] = []
    aligned_returns = returns.loc[strategy_returns.index]
    if benchmark in aligned_returns.columns:
        benchmarks.append(
            _benchmark_from_returns(
                key="symbol",
                label=f"{benchmark} 基准",
                symbol=benchmark,
                returns=aligned_returns[benchmark].fillna(0.0),
            )
        )
    else:
        notes.append(
            BacktestDataNote(
                severity="warning",
                message=f"本地数据缺少 {benchmark}，已跳过该基准。",
            )
        )
    universe_returns = aligned_returns.mean(axis=1, skipna=True).fillna(0.0)
    benchmarks.append(
        _benchmark_from_returns(
            key="universe_equal_weight",
            label="ETF池等权基准",
            returns=universe_returns,
        )
    )
    notes.append(
        BacktestDataNote(
            message=(
                "信号在调仓日收盘后读取，组合收益从下一交易日开始计算，"
                f"单边成本 {cost_bps:g}bp。"
            )
        )
    )
    if len(snapshots) < PRODUCTION_MIN_REBALANCES:
        notes.append(
            BacktestDataNote(
                severity="warning",
                message=(
                    f"当前仅 {len(snapshots)} 次月度调仓，低于生产门槛 "
                    f"{PRODUCTION_MIN_REBALANCES} 次；结果只能作为研究候选。"
                ),
            )
        )

    return BacktestResult(
        config=config,
        metrics=metrics,
        equity_curve=equity_curve,
        benchmarks=benchmarks,
        holdings=snapshots,
        risk_summary=_risk_summary(snapshots),
        validation=_validation_summary(
            metrics=metrics,
            benchmarks=benchmarks,
            benchmark=benchmark,
            rebalance_count=len(snapshots),
        ),
        data_notes=notes,
    )


def _walk_forward_cache_key(
    start: date | None,
    end: date | None,
    train_months: int,
    test_months: int,
    step_months: int,
    top_n: int,
    cost_bps: float,
) -> tuple[object, ...]:
    return (
        "walk_forward",
        start,
        end,
        train_months,
        test_months,
        step_months,
        top_n,
        cost_bps,
        clean_data_fingerprint(
            ["etf_daily.parquet", "etf_basic.parquet", "factors_processed.parquet"]
        ),
    )


def run_walk_forward_analysis(
    start: date | None = None,
    end: date | None = None,
    train_months: int = 24,
    test_months: int = 6,
    step_months: int = 6,
    top_n: int = 10,
    cost_bps: float = 5.0,
) -> dict:
    cache_key = _walk_forward_cache_key(
        start,
        end,
        train_months,
        test_months,
        step_months,
        top_n,
        cost_bps,
    )
    return _WALK_FORWARD_CACHE.get_or_create(
        cache_key,
        lambda: _run_walk_forward_analysis_uncached(
            start=start,
            end=end,
            train_months=train_months,
            test_months=test_months,
            step_months=step_months,
            top_n=top_n,
            cost_bps=cost_bps,
        ),
    )


def _run_walk_forward_analysis_uncached(
    start: date | None = None,
    end: date | None = None,
    train_months: int = 24,
    test_months: int = 6,
    step_months: int = 6,
    top_n: int = 10,
    cost_bps: float = 5.0,
) -> dict:
    """Walk-forward validation entry point. Returns a JSON-serializable result."""
    from datetime import UTC, datetime

    from app.backtest.walk_forward import WalkForwardConfig
    from app.backtest.walk_forward import run_walk_forward as _run_wf
    from app.models.walk_forward import (
        WalkForwardConfigModel,
        WalkForwardResultModel,
        WalkForwardWindowModel,
    )
    from app.synthesis import icir_weights

    daily = _clean_daily()
    factors = _read_factors(processed=True)
    if daily.empty or factors.empty:
        return _empty_walk_forward_result(
            train_months, test_months, step_months, top_n, cost_bps,
            "缺少日线或处理后因子数据，请先采集数据并重建因子。",
        )

    if start is not None:
        daily = daily[daily["date"] >= start]
    if end is not None:
        daily = daily[daily["date"] <= end]

    config = WalkForwardConfig(
        train_months=train_months,
        test_months=test_months,
        step_months=step_months,
        top_n=top_n,
        cost_bps=cost_bps,
    )

    def _eval_fn(factors_df, daily_df, t_start, t_end):
        """Lightweight eval — only compute IC stats + correlation, skip quantile/turnover."""
        from app.models.evaluation import FactorEvaluationReport

        dates = sorted(factors_df["date"].unique())
        end_date = dates[-1] if dates else t_end
        horizon = 20  # single horizon is enough for ICIR weighting

        reports_list: list = []
        for name in factors_df["factor_name"].unique():
            try:
                ic = calculate_ic_stats(
                    name,
                    start=t_start,
                    end=end_date,
                    horizon=horizon,
                    horizons=[horizon],
                    processed=True,
                )
                # Build a minimal report — icir_weights only reads .ic.icir and .ic.ic_pos_ratio
                reports_list.append(
                    FactorEvaluationReport(
                        factor_name=name,
                        generated_at=datetime.now(UTC),
                        ic=ic,
                    )
                )
            except Exception:
                continue
        corr = calculate_factor_correlation_matrix(end=end_date, processed=True)
        return reports_list, corr

    def _weight_fn(reports_list, corr_matrix):
        return icir_weights(reports_list, corr_matrix)

    def _score_fn(factors_df, weights):
        return _score_frame(factors_df, weights)

    def _rebalance_fn(scores, daily_df, trading_dates, n):
        return _select_rebalances(scores, daily_df, trading_dates, n)

    result = _run_wf(
        daily,
        factors,
        _eval_fn,
        _weight_fn,
        _score_fn,
        _rebalance_fn,
        config=config,
    )

    windows_model = [
        WalkForwardWindowModel(
            train_start=win.train_start,
            train_end=win.train_end,
            test_start=win.test_start,
            test_end=win.test_end,
            selected_factors=win.selected_factors,
            factor_weights=win.factor_weights,
            train_icir=win.train_icir,
            test_metrics=win.test_metrics or BacktestMetrics(),
            test_equity_curve=win.test_equity_curve,
        )
        for win in result.windows
    ]

    return WalkForwardResultModel(
        config=WalkForwardConfigModel(
            train_months=config.train_months,
            test_months=config.test_months,
            step_months=config.step_months,
            top_n=config.top_n,
            cost_bps=config.cost_bps,
        ),
        windows=windows_model,
        oos_equity_curve=result.oos_equity_curve,
        oos_metrics=result.oos_metrics or BacktestMetrics(),
        is_metrics=result.is_metrics or BacktestMetrics(),
        factor_stability=result.factor_stability,
        weight_stability=result.weight_stability,
        overfit_warning=result.overfit_warning,
        data_notes=result.data_notes,
        generated_at=datetime.now(UTC),
    ).model_dump()


def _empty_walk_forward_result(
    train_months: int,
    test_months: int,
    step_months: int,
    top_n: int,
    cost_bps: float,
    message: str,
) -> dict:
    from app.models.walk_forward import (
        WalkForwardConfigModel,
        WalkForwardResultModel,
    )
    return WalkForwardResultModel(
        config=WalkForwardConfigModel(
            train_months=train_months,
            test_months=test_months,
            step_months=step_months,
            top_n=top_n,
            cost_bps=cost_bps,
        ),
        oos_metrics=BacktestMetrics(),
        is_metrics=BacktestMetrics(),
        data_notes=[message],
    ).model_dump()
