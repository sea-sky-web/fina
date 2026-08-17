"""Tests for the rotation backtest engine (app.rotation_engine)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.rotation_engine.config import StrategyConfig
from app.rotation_engine.engine import (
    simulate,
    target_symbols_hysteresis,
    target_weights,
)
from app.rotation_engine.metrics import (
    annualized_return,
    calmar_ratio,
    max_drawdown,
    max_drawdown_with_dates,
    sharpe_ratio,
)
from app.rotation_engine.signals import (
    compute_scores,
    vectorized_pct_rank,
    vectorized_zscore,
)
from app.rotation_engine.walkforward import build_windows_expanding

TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def test_annualized_return_of_constant_daily_return() -> None:
    r = pd.Series([0.001] * TRADING_DAYS)
    expected = 1.001 ** TRADING_DAYS - 1
    assert annualized_return(r) == pytest.approx(expected, rel=1e-9)


def test_annualized_return_empty_series_is_zero() -> None:
    assert annualized_return(pd.Series(dtype=float)) == 0.0


def test_max_drawdown_known_path() -> None:
    # equity: 1.0 -> 1.1 -> 0.88 -> 0.968  => max dd = 0.88/1.1 - 1 = -20%
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    r = pd.Series([0.10, -0.20, 0.10], index=idx)
    mdd, peak, trough = max_drawdown_with_dates(r)
    assert mdd == pytest.approx(-0.20)
    assert peak == str(idx[0].date())
    assert trough == str(idx[1].date())


def test_max_drawdown_never_negative_returns_zero_dd() -> None:
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    r = pd.Series([0.01, 0.02, 0.005], index=idx)
    assert max_drawdown(r) == pytest.approx(0.0)


def test_sharpe_ratio_zero_variance_is_zero() -> None:
    assert sharpe_ratio(pd.Series([0.01, 0.01, 0.01])) == 0.0


def test_sharpe_ratio_sign_follows_mean() -> None:
    rng = np.random.default_rng(7)
    up = pd.Series(rng.normal(0.005, 0.01, 500))
    down = pd.Series(rng.normal(-0.005, 0.01, 500))
    assert sharpe_ratio(up) > 0
    assert sharpe_ratio(down) < 0


def test_calmar_ratio_zero_when_no_drawdown() -> None:
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    assert calmar_ratio(pd.Series([0.01, 0.01], index=idx)) == 0.0


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------

def test_vectorized_zscore_row_mean_zero_and_zero_std_fill() -> None:
    frame = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 2.0], "c": [5.0, 2.0]})
    z = vectorized_zscore(frame)
    assert z.iloc[0].mean() == pytest.approx(0.0)
    # second row has zero cross-sectional std -> filled with 0
    assert (z.iloc[1] == 0.0).all()


def test_vectorized_pct_rank_orders_and_fills_nan() -> None:
    frame = pd.DataFrame({"a": [1.0], "b": [2.0], "c": [np.nan]})
    ranked = vectorized_pct_rank(frame)
    assert ranked.loc[0, "b"] > ranked.loc[0, "a"]
    assert ranked.loc[0, "c"] == 0.5


def _synthetic_market(n_days: int = 200, seed: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Benchmark + three ETFs with distinct drifts, plus amounts."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=n_days)
    def walk(drift: float) -> np.ndarray:
        return 1.0 * np.cumprod(1 + rng.normal(drift, 0.01, n_days))
    close = pd.DataFrame(
        {
            "510300.SH": walk(0.0002),
            "STRONG": walk(0.003),
            "FLAT": walk(0.0),
            "WEAK": walk(-0.003),
        },
        index=idx,
    )
    amount = pd.DataFrame(1e8, index=idx, columns=close.columns)
    return close, amount


def test_compute_scores_warmup_nan_then_ranks_strong_above_weak() -> None:
    close, amount = _synthetic_market()
    symbols = ["STRONG", "FLAT", "WEAK"]
    cfg = StrategyConfig()
    scores = compute_scores(close, symbols, amount, cfg)

    assert list(scores.columns) == symbols
    # warmup: before rel_strength_lookback data the score must be NaN
    assert scores.iloc[: cfg.rel_strength_lookback].isna().all().all()
    last = scores.iloc[-1]
    assert last["STRONG"] > last["WEAK"]


def test_compute_scores_empty_symbols_returns_empty_frame() -> None:
    close, amount = _synthetic_market(n_days=80)
    scores = compute_scores(close, [], amount, StrategyConfig())
    assert scores.empty or scores.shape[1] == 0


# ---------------------------------------------------------------------------
# engine: selection and weights
# ---------------------------------------------------------------------------

def test_hysteresis_keeps_held_symbol_within_buffer() -> None:
    score = pd.Series({"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.5})
    held = pd.Series({"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.5})
    # K=2, buffer=3 -> top_k_buffer covers d, so held d survives over higher-ranked b
    selected = target_symbols_hysteresis(score, held, 2, set(), set(), 3)
    assert "d" in selected
    assert len(selected) == 2
    assert selected[0] == "d" or "a" in selected


def test_hysteresis_excludes_cooldown_and_negative_scores() -> None:
    score = pd.Series({"a": 5.0, "b": 4.0, "c": -1.0})
    none_held = pd.Series(0.0, index=["a", "b", "c"])
    selected = target_symbols_hysteresis(score, none_held, 2, set(), {"a"}, 2)
    assert selected == ["b"]  # a in cooldown, c has negative score


def test_hysteresis_drops_stopped_out_holding() -> None:
    score = pd.Series({"a": 5.0, "b": 4.0, "c": 3.0})
    held = pd.Series({"a": 0.5, "b": 0.0, "c": 0.0})
    selected = target_symbols_hysteresis(score, held, 1, {"a"}, {"a"}, 2)
    assert selected == ["b"]


def test_target_weights_equal_weight_with_cap() -> None:
    w = target_weights(["a", "b"], ["a", "b", "c"], "510300.SH", max_symbol_weight=0.25)
    assert w["a"] == pytest.approx(0.25)  # capped from 0.5
    assert w["c"] == 0.0


def test_target_weights_bench_slot_included() -> None:
    w = target_weights(["a"], ["a", "b"], "510300.SH", max_symbol_weight=0.6, bench_slot=True)
    assert w["510300.SH"] == pytest.approx(0.5)
    assert w["a"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# engine: simulate
# ---------------------------------------------------------------------------

def _simulate_setup(n_days: int = 200):
    close, amount = _synthetic_market(n_days=n_days)
    symbols = ["STRONG", "FLAT", "WEAK"]
    cfg = StrategyConfig()
    scores = compute_scores(close, symbols, amount, cfg)
    returns = close[symbols].pct_change()
    dates = close.index[cfg.rel_strength_lookback + 10 :]
    return scores, returns, close, symbols, dates, cfg


def test_simulate_produces_daily_records_with_costs() -> None:
    scores, returns, close, symbols, dates, cfg = _simulate_setup()
    sim = simulate(scores, returns, close, symbols, dates, 2, cfg)

    assert len(sim) == len(dates)
    assert {"gross_return", "cost", "net_return", "turnover", "n_holdings"} <= set(sim.columns)
    assert (sim["cost"] >= 0).all()
    assert (sim["turnover"] <= cfg.max_daily_turnover + 1e-9).all()
    # cost must equal turnover * one-side rate whenever no circuit breaker fired
    normal = sim[sim["cost"] > 0]
    pd.testing.assert_series_equal(
        normal["cost"],
        normal["turnover"] * cfg.cost_rate_one_side,
        check_names=False,
    )


def test_simulate_stop_loss_triggers_on_crash() -> None:
    close, amount = _synthetic_market(n_days=160, seed=11)
    symbols = ["STRONG", "FLAT", "WEAK"]
    cfg = StrategyConfig(stop_loss_threshold=-0.05, cooldown_days=5)
    # engineer a crash right after the simulation start, when the position
    # has just been entered and the entry price is still close to the peak
    sim_start = cfg.rel_strength_lookback + 10
    crash_start = sim_start + 5
    close.iloc[crash_start:, close.columns.get_loc("STRONG")] *= np.cumprod(
        np.full(len(close) - crash_start, 0.90)
    )
    scores = compute_scores(close, symbols, amount, cfg)
    returns = close[symbols].pct_change()
    dates = close.index[sim_start:]
    sim = simulate(scores, returns, close, symbols, dates, 1, cfg)
    assert sim.attrs["stop_loss_events"] >= 1


def test_simulate_empty_dates_returns_empty() -> None:
    scores, returns, close, symbols, _, cfg = _simulate_setup(n_days=120)
    sim = simulate(scores, returns, close, symbols, pd.DatetimeIndex([]), 2, cfg)
    assert sim.empty


# ---------------------------------------------------------------------------
# walk-forward windows
# ---------------------------------------------------------------------------

def test_build_windows_expanding_no_overlap_and_embargo() -> None:
    dates = pd.bdate_range("2020-01-01", periods=400)
    cfg = StrategyConfig(min_train_days=250, test_trading_days=42, step_trading_days=21)
    windows = build_windows_expanding(dates, cfg)

    assert windows, "expected at least one window"
    prev_train_len = 0
    for train, test in windows:
        assert train[-1] < test[0], "train must end before test starts"
        assert (test[0] - train[-1]).days >= 1, "embargo gap violated"
        assert len(test) == cfg.test_trading_days
        assert len(train) > prev_train_len, "training window must expand"
        prev_train_len = len(train)


def test_build_windows_expanding_too_little_data_gives_no_windows() -> None:
    dates = pd.bdate_range("2020-01-01", periods=100)
    cfg = StrategyConfig(min_train_days=250)
    assert build_windows_expanding(dates, cfg) == []
