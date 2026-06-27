from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import sqrt

import pandas as pd

from app.models.etf import BacktestEquityPoint, BacktestMetrics

TRADING_DAYS_PER_MONTH = 21
TRADING_DAYS_PER_YEAR = 252


@dataclass
class WalkForwardConfig:
    train_months: int = 24
    test_months: int = 6
    step_months: int = 6
    top_n: int = 10
    cost_bps: float = 5.0


@dataclass
class WalkForwardWindow:
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    selected_factors: list[str] = field(default_factory=list)
    factor_weights: dict[str, float] = field(default_factory=dict)
    train_icir: dict[str, float | None] = field(default_factory=dict)
    test_metrics: BacktestMetrics | None = None
    test_equity_curve: list[BacktestEquityPoint] = field(default_factory=list)


@dataclass
class WalkForwardResult:
    config: WalkForwardConfig
    windows: list[WalkForwardWindow] = field(default_factory=list)
    oos_equity_curve: list[BacktestEquityPoint] = field(default_factory=list)
    oos_metrics: BacktestMetrics | None = None
    is_metrics: BacktestMetrics | None = None
    factor_stability: float = 0.0
    weight_stability: dict[str, float | None] = field(default_factory=dict)
    overfit_warning: str = ""
    data_notes: list[str] = field(default_factory=list)


def _monthly_date_range(
    daily_dates: list[date],
    start: date,
    end: date,
) -> list[date]:
    """Return date anchors spaced by calendar months within [start, end]."""
    if not daily_dates:
        return []
    anchors: list[date] = []
    current = start
    while current <= end:
        candidates = [value for value in daily_dates if value >= current]
        if not candidates:
            break
        anchors.append(candidates[0])
        if current.month == 12:
            current = date(current.year + 1, 1, current.day)
        else:
            try:
                current = date(current.year, current.month + 1, current.day)
            except ValueError:
                current = date(current.year, current.month + 2, 1)
    return anchors


def _jaccard_stability(windows: list[WalkForwardWindow]) -> float:
    if len(windows) < 2:
        return 1.0
    similarities: list[float] = []
    for previous, current in zip(windows, windows[1:], strict=False):
        previous_set = set(previous.selected_factors)
        current_set = set(current.selected_factors)
        union = previous_set | current_set
        if not union:
            similarities.append(1.0)
            continue
        similarities.append(len(previous_set & current_set) / len(union))
    return float(sum(similarities) / len(similarities)) if similarities else 1.0


def _weight_cv(windows: list[WalkForwardWindow]) -> dict[str, float | None]:
    all_factors: set[str] = set()
    for window in windows:
        all_factors.update(window.factor_weights)
    stability: dict[str, float | None] = {}
    for factor_name in all_factors:
        values = [
            window.factor_weights.get(factor_name, 0.0)
            for window in windows
        ]
        series = pd.Series(values, dtype="float64")
        mean = series.mean()
        if mean == 0:
            stability[factor_name] = None
        else:
            stability[factor_name] = float(series.std(ddof=1) / mean) if len(series) > 1 else None
    return stability


def _period_metrics(
    returns: pd.Series,
    equity: pd.Series,
    average_turnover: float,
    rebalance_count: int,
) -> BacktestMetrics:
    clean_returns = pd.to_numeric(returns, errors="coerce").dropna()
    clean_equity = pd.to_numeric(equity, errors="coerce").dropna()
    if clean_equity.empty:
        return BacktestMetrics(average_turnover=average_turnover, rebalance_count=rebalance_count)

    cumulative_return = float(clean_equity.iloc[-1] - 1)
    periods = max(len(clean_returns), 1)
    annualized_return = float(
        clean_equity.iloc[-1] ** (TRADING_DAYS_PER_YEAR / periods) - 1
    )
    annualized_volatility = float(
        clean_returns.std(ddof=0) * sqrt(TRADING_DAYS_PER_YEAR)
    )
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
        rebalance_count=rebalance_count,
        final_equity=float(clean_equity.iloc[-1]),
    )


def _equity_curve_from_returns(returns: pd.Series) -> tuple[list[BacktestEquityPoint], pd.Series]:
    clean = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    equity = (1 + clean).cumprod()
    points = [
        BacktestEquityPoint(
            date=index,
            equity=float(value),
            daily_return=float(clean.loc[index]),
        )
        for index, value in equity.items()
    ]
    return points, equity


def run_walk_forward(
    daily: pd.DataFrame,
    factors_processed: pd.DataFrame,
    eval_fn,
    weight_fn,
    score_fn,
    rebalance_fn,
    config: WalkForwardConfig | None = None,
) -> WalkForwardResult:
    """Run a walk-forward validation across rolling training/test windows.

    Args:
        daily: Clean daily data (symbol, date, close, amount).
        factors_processed: Processed factor data (symbol, date, factor_name, ...).
        eval_fn: (factors, daily, train_start, train_end) -> factor evaluation reports.
        weight_fn: (eval_reports, correlation_matrix) -> dict[str, float] weights.
        score_fn: (factors, weights) -> DataFrame with (date, symbol, research_score).
        rebalance_fn: (scores, daily, trading_dates, top_n) -> list of selections.
        config: Walk-forward parameters.

    Returns:
        WalkForwardResult with per-window details and aggregated OOS/IS comparison.
    """
    cfg = config or WalkForwardConfig()
    if daily.empty or factors_processed.empty:
        return WalkForwardResult(
            config=cfg,
            data_notes=["缺少日线或处理后因子数据，无法进行 Walk-forward 验证。"],
        )

    daily_dates = sorted(daily["date"].dropna().unique())
    if len(daily_dates) < (cfg.train_months + cfg.test_months) * TRADING_DAYS_PER_MONTH:
        return WalkForwardResult(
            config=cfg,
            data_notes=["可用历史交易日不足以支撑 Walk-forward 窗口划分。"],
        )

    factor_names = sorted(factors_processed["factor_name"].dropna().unique())
    if not factor_names:
        return WalkForwardResult(
            config=cfg,
            data_notes=["处理后因子数据不包含任何因子列。"],
        )

    factors = factors_processed.copy()
    factors["date"] = pd.to_datetime(factors["date"]).dt.date
    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date

    start_date = daily_dates[0]
    end_date = daily_dates[-1]
    train_days = cfg.train_months * TRADING_DAYS_PER_MONTH
    test_days = cfg.test_months * TRADING_DAYS_PER_MONTH
    step_days = cfg.step_months * TRADING_DAYS_PER_MONTH

    anchor_dates = _monthly_date_range(daily_dates, start_date, end_date)
    if len(anchor_dates) < 3:
        return WalkForwardResult(
            config=cfg,
            data_notes=["月度锚点日期不足，无法划分 Walk-forward 窗口。"],
        )

    windows: list[WalkForwardWindow] = []
    all_test_returns: list[pd.Series] = []

    anchor_index = 0
    while anchor_index + 2 < len(anchor_dates):
        train_start = anchor_dates[anchor_index]
        train_candidates = [value for value in daily_dates if value > train_start]
        if len(train_candidates) < train_days:
            break
        train_end = train_candidates[train_days - 1]

        test_candidates = [value for value in daily_dates if value > train_end]
        if len(test_candidates) < test_days:
            break
        test_start = test_candidates[0]
        test_end = test_candidates[min(test_days - 1, len(test_candidates) - 1)]

        train_daily = daily[(daily["date"] >= train_start) & (daily["date"] <= train_end)]
        train_factors = factors[
            (factors["date"] >= train_start) & (factors["date"] <= train_end)
        ]
        test_daily = daily[(daily["date"] >= test_start) & (daily["date"] <= test_end)]
        test_factors = factors[
            (factors["date"] >= test_start) & (factors["date"] <= test_end)
        ]

        if train_daily.empty or train_factors.empty:
            anchor_index += 1
            continue

        try:
            eval_reports, correlation_matrix = eval_fn(
                train_factors, train_daily, train_start, train_end
            )
        except Exception:
            anchor_index += 1
            continue

        weights = weight_fn(eval_reports, correlation_matrix)
        if not weights:
            anchor_index += 1
            continue

        train_icir = {
            report.factor_name: report.ic.icir
            for report in eval_reports
            if report.ic.icir is not None
        }
        selected_factors = sorted(weights)

        test_score = score_fn(test_factors, weights)
        if test_score.empty or test_daily.empty:
            anchor_index += 1
            continue

        test_trading_dates = sorted(test_daily["date"].unique())
        selections = rebalance_fn(test_score, test_daily, test_trading_dates, cfg.top_n)
        selections = [item for item in selections if item.effective_date is not None]
        if len(selections) < 1:
            anchor_index += 1
            continue

        prices = test_daily.pivot_table(
            index="date", columns="symbol", values="close", aggfunc="last"
        ).sort_index()
        price_returns = prices.pct_change()
        cost_rate = cfg.cost_bps / 10000

        strategy_returns = pd.Series(0.0, index=price_returns.index)
        old_weights: dict[str, float] = {}
        turnovers: list[float] = []

        for sel_index, selection in enumerate(selections):
            next_effective = (
                selections[sel_index + 1].effective_date
                if sel_index + 1 < len(selections)
                else None
            )
            period_mask = price_returns.index >= selection.effective_date
            if next_effective is not None:
                period_mask &= price_returns.index < next_effective
            selected = price_returns.loc[period_mask, selection.symbols]
            selected = selected.dropna(axis=1, how="all")
            period_returns = selected.mean(axis=1, skipna=True).fillna(0.0)
            new_weight = 1 / len(selection.symbols) if selection.symbols else 0.0
            new_weights = {sym: new_weight for sym in selection.symbols}
            if old_weights:
                all_symbols = set(old_weights) | set(new_weights)
                turnover = (
                    sum(
                        abs(new_weights.get(sym, 0.0) - old_weights.get(sym, 0.0))
                        for sym in all_symbols
                    )
                    / 2
                )
            else:
                turnover = 1.0
            cost = turnover * cost_rate
            if not period_returns.empty:
                period_returns.iloc[0] = period_returns.iloc[0] - cost
                strategy_returns.loc[period_returns.index] = period_returns
            turnovers.append(turnover)
            old_weights = new_weights

        first_effective = selections[0].effective_date
        strategy_returns = strategy_returns[strategy_returns.index >= first_effective]
        if strategy_returns.empty:
            anchor_index += 1
            continue

        curve_points, equity = _equity_curve_from_returns(strategy_returns)
        avg_turnover = float(pd.Series(turnovers).mean()) if turnovers else 0.0
        test_metrics = _period_metrics(strategy_returns, equity, avg_turnover, len(selections))

        windows.append(
            WalkForwardWindow(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                selected_factors=selected_factors,
                factor_weights=weights,
                train_icir=train_icir,
                test_metrics=test_metrics,
                test_equity_curve=curve_points,
            )
        )
        all_test_returns.append(strategy_returns)
        anchor_index += max(1, step_days // TRADING_DAYS_PER_MONTH)

    if not windows:
        return WalkForwardResult(
            config=cfg,
            data_notes=["Walk-forward 窗口划分后无一产生有效结果。"],
        )

    # Concatenate OOS returns
    combined_returns = pd.concat(all_test_returns).sort_index()
    combined_returns = combined_returns[~combined_returns.index.duplicated(keep="first")]
    oos_points, oos_equity = _equity_curve_from_returns(combined_returns)
    oos_metrics = _period_metrics(
        combined_returns,
        oos_equity,
        0.0,
        sum(len(win.test_equity_curve) for win in windows),
    )

    # In-sample metrics via full-sample backtest (for comparison)
    full_factors = factors.copy()
    full_weights, _ = weight_fn(
        eval_fn(full_factors, daily, start_date, end_date)[0],
        eval_fn(full_factors, daily, start_date, end_date)[1],
    )
    full_score = score_fn(full_factors, full_weights)
    full_trading_dates = sorted(daily_dates)
    full_selections = rebalance_fn(full_score, daily, full_trading_dates, cfg.top_n)
    full_selections = [item for item in full_selections if item.effective_date is not None]
    is_metrics = BacktestMetrics()
    if len(full_selections) >= 2:
        prices = daily.pivot_table(
            index="date", columns="symbol", values="close", aggfunc="last"
        ).sort_index()
        price_returns = prices.pct_change()
        strat_returns = pd.Series(0.0, index=price_returns.index)
        for sel_index, selection in enumerate(full_selections):
            next_eff = (
                full_selections[sel_index + 1].effective_date
                if sel_index + 1 < len(full_selections)
                else None
            )
            mask = price_returns.index >= selection.effective_date
            if next_eff is not None:
                mask &= price_returns.index < next_eff
            sel_ret = price_returns.loc[mask, selection.symbols]
            sel_ret = sel_ret.dropna(axis=1, how="all")
            period = sel_ret.mean(axis=1, skipna=True).fillna(0.0)
            strat_returns.loc[period.index] = period
        first = full_selections[0].effective_date
        strat_returns = strat_returns[strat_returns.index >= first]
        _, is_eq = _equity_curve_from_returns(strat_returns)
        is_metrics = _period_metrics(strat_returns, is_eq, 0.0, len(full_selections))

    factor_stability = _jaccard_stability(windows)
    weight_stability = _weight_cv(windows)

    # Overfit assessment
    oos_ann = oos_metrics.annualized_return or 0.0
    is_ann = is_metrics.annualized_return or 0.0
    spread = oos_ann - is_ann
    if spread < -0.15:
        overfit_warning = "严重过拟合 — 样本外年化收益比样本内低 15% 以上，策略不可靠。"
    elif spread < -0.05:
        overfit_warning = "轻微过拟合 — 样本外表现弱于样本内，建议继续观察更多窗口。"
    elif factor_stability < 0.4:
        overfit_warning = "因子选择不稳定 — 各窗口选中的因子差异大，信号可能依赖特定市场阶段。"
    else:
        overfit_warning = "样本内外表现一致，当前窗口划分下未检测到严重过拟合。"

    data_notes = [
        (
            f"Walk-forward: {cfg.train_months}月训练 / {cfg.test_months}月测试 / "
            f"步长{cfg.step_months}月，共 {len(windows)} 个有效窗口。"
        ),
        "每个窗口在训练期独立评估因子、确定权重，在测试期做纯样本外验证。",
        "样本外净值曲线由各窗口测试期拼接而成。",
        "本验证仅用于研究参考，不构成投资建议。",
    ]

    return WalkForwardResult(
        config=cfg,
        windows=windows,
        oos_equity_curve=oos_points,
        oos_metrics=oos_metrics,
        is_metrics=is_metrics,
        factor_stability=factor_stability,
        weight_stability=weight_stability,
        overfit_warning=overfit_warning,
        data_notes=data_notes,
    )
