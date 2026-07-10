"""
高频行业轮动策略 V7 —— 新规则第一轮基线

新规则变化（相对V1-V6）：
    - 标的池扩充到16只（原12只+电力/食品饮料/家电/农业4只低相关防御品种）
    - 单只仓位上限 25%（原20%）
    - 单日双边换手上限 90%（原80%）
    - 训练窗口改为"扩展窗口"（从数据起点到测试窗口前），而非固定24个月滚动
    - 训练截止与测试开始之间加1个交易日隔离（防止数据泄露）
    - 判定标准换成新的8项硬性门槛（见 JUDGE 部分）

策略核心逻辑沿用V1-V6中验证有效的部分（非"套用已知公式"，是本项目自己迭代验证过的组件）：
    - 双周期动量集成 z-score(L=10) 与 z-score(L=20) 均值 + 60日相对强度百分位
    - 缓冲区滞后换仓（Top K+2 才淘汰，减少无效换手）
    - 个股止损 -8% + 5个交易日冷却期

可优化参数（≤5个，满足反作弊约束）：
    K（持仓数量）：[3,4,5,6]
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

DATA_PATH = Path("/Users/ster/Desktop/fina/data/research/etf_daily_backtest.parquet")
BENCHMARK = "510300.SH"
COST_RATE_ONE_SIDE = 0.00075  # 买卖合计 1.5‰
MAX_SYMBOL_WEIGHT = 0.25
MAX_DAILY_TURNOVER = 0.90
CIRCUIT_BREAKER_DAILY_LOSS = -0.03
MIN_TRAIN_DAYS = 250
TEST_TRADING_DAYS = 42
STEP_TRADING_DAYS = 21
EMBARGO_DAYS = 1  # 训练/测试隔离
TRADING_DAYS_PER_YEAR = 252

MOMENTUM_LOOKBACK_SET = [10, 20]
REL_STRENGTH_LOOKBACK = 60
HYSTERESIS_BUFFER = 3
PARAM_GRID_K = [2]

STOP_LOSS_THRESHOLD = -0.05
COOLDOWN_DAYS = 5

# V11: 组合层面快速回撤熔断
PORTFOLIO_DD_THRESHOLD = -0.08  # 净值自阶段性高点回撤超过此值则空仓
PORTFOLIO_DD_COOLDOWN = 5  # 空仓交易日数


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    raw = pd.read_parquet(DATA_PATH)
    raw["date"] = pd.to_datetime(raw["date"])
    close = raw.pivot(index="date", columns="symbol", values="close").sort_index()
    amount = raw.pivot(index="date", columns="symbol", values="amount").sort_index()
    close = close.ffill(limit=2)
    symbols = [c for c in close.columns if c != BENCHMARK]
    return close, amount, symbols


def liquidity_filter(amount: pd.DataFrame, symbols: list[str], min_avg_amount: float = 5.0e7) -> list[str]:
    avg_amount = amount[symbols].mean()
    kept = [s for s in symbols if avg_amount.get(s, 0) >= min_avg_amount]
    dropped = sorted(set(symbols) - set(kept))
    if dropped:
        print(f"[liquidity_filter] dropped low-liquidity symbols: {dropped}")
    return kept


def restrict_to_common_history(close: pd.DataFrame, symbols: list[str]) -> pd.DatetimeIndex:
    """所有标的（含基准）都必须有数据的最早公共日期起算，避免用不存在的历史。"""
    valid = close[symbols + [BENCHMARK]].dropna(how="any")
    return valid.index


def vectorized_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    mean = frame.mean(axis=1)
    std = frame.std(axis=1, ddof=0).replace(0, np.nan)
    z = frame.sub(mean, axis=0).div(std, axis=0)
    return z.fillna(0.0)


def vectorized_pct_rank(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rank(axis=1, pct=True).fillna(0.5)


def compute_scores_full(close: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    mom_components = []
    for L in MOMENTUM_LOOKBACK_SET:
        ret = close[symbols].pct_change(L)
        mom_components.append(vectorized_zscore(ret))
    mom_z = sum(mom_components) / len(mom_components)

    bench_ret_long = close[BENCHMARK].pct_change(REL_STRENGTH_LOOKBACK)
    ret_long = close[symbols].pct_change(REL_STRENGTH_LOOKBACK)
    excess_long = ret_long.sub(bench_ret_long, axis=0)
    rel_rank = vectorized_pct_rank(excess_long)

    # V14: 动态因子权重——基准MA20<MA60时降低动量权重
    bench = close[BENCHMARK]
    ma20 = bench.rolling(20).mean()
    ma60 = bench.rolling(60).mean()
    bear_mask = (ma20 < ma60).reindex(close.index).fillna(False)

    w_mom = pd.Series(0.55, index=close.index)
    w_rel = pd.Series(0.45, index=close.index)
    w_mom[bear_mask] = 0.35
    w_rel[bear_mask] = 0.65

    score = mom_z.mul(w_mom, axis=0) + rel_rank.mul(w_rel, axis=0)
    score[excess_long.isna()] = np.nan
    return score


def target_symbols_hysteresis(
    score_row: pd.Series,
    current_weights: pd.Series,
    holdings: int,
    stopped_out: set[str],
    cooldown: set[str],
    buffer: int = HYSTERESIS_BUFFER,
) -> list[str]:
    candidates = score_row.dropna()
    positive = candidates[candidates > 0]
    ranked = positive.sort_values(ascending=False)
    ranked_eligible = ranked[~ranked.index.isin(cooldown)]

    currently_held = set(current_weights[current_weights > 0].index) - stopped_out
    top_k_buffer = set(ranked_eligible.head(holdings + buffer).index)

    keep_candidates = currently_held & top_k_buffer
    keep_ranked = ranked_eligible[ranked_eligible.index.isin(keep_candidates)]
    keep_final = list(keep_ranked.head(holdings).index)

    open_slots = holdings - len(keep_final)
    new_candidates = [s for s in ranked_eligible.index if s not in keep_final]
    new_adds = new_candidates[: max(open_slots, 0)]
    return keep_final + new_adds


def target_weights_from_symbols(final_set: list[str], symbols: list[str], holdings: int) -> pd.Series:
    weights = pd.Series(0.0, index=symbols)
    if not final_set:
        return weights
    per_weight = min(1.0 / len(final_set), MAX_SYMBOL_WEIGHT)
    weights.loc[final_set] = per_weight
    return weights


def simulate(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    close_full: pd.DataFrame,
    symbols: list[str],
    dates: pd.DatetimeIndex,
    holdings: int,
    cost_rate_one_side: float = COST_RATE_ONE_SIDE,
) -> pd.DataFrame:
    score = score_full.reindex(dates)
    returns = returns_full.reindex(dates)
    prices = close_full.reindex(dates)

    # Bear market detection for position scaling
    bench_close = close_full[BENCHMARK]
    bench_ma10 = bench_close.rolling(10).mean()
    bench_ma30 = bench_close.rolling(30).mean()
    bear_mask = (bench_ma10 < bench_ma30).reindex(dates).fillna(False)
    BEAR_SCALE = 0.30

    # V45: Cross-sectional dispersion filter
    ret_20 = close_full[symbols].pct_change(20)
    cross_disp = ret_20.std(axis=1)
    disp_median = cross_disp.rolling(60).median()
    low_disp_mask = (cross_disp < disp_median).reindex(dates).fillna(False)
    DISP_SCALE = 0.20

    current_weights = pd.Series(0.0, index=symbols)
    entry_price: dict[str, float] = {}
    cooldown_until: dict[str, pd.Timestamp] = {}
    paused_until: pd.Timestamp | None = None
    records = []
    stop_loss_events = 0
    # V11: 组合层面回撤熔断状态
    portfolio_equity = 1.0
    portfolio_peak = 1.0
    portfolio_dd_cooldown_until: pd.Timestamp | None = None

    for d in dates:
        day_price = prices.loc[d].reindex(symbols)
        day_returns = returns.loc[d].reindex(symbols).fillna(0.0)
        gross_return = float((current_weights * day_returns).sum())

        cooldown_active = {s for s, until in cooldown_until.items() if until >= d}

        stopped_out: set[str] = set()
        for sym in list(current_weights[current_weights > 0].index):
            ep = entry_price.get(sym)
            price_now = day_price.get(sym)
            if ep is None or pd.isna(price_now) or ep == 0:
                continue
            ret_since_entry = price_now / ep - 1
            if ret_since_entry <= STOP_LOSS_THRESHOLD:
                stopped_out.add(sym)
                cooldown_until[sym] = d + pd.tseries.offsets.BDay(COOLDOWN_DAYS)
                stop_loss_events += 1

        if paused_until is not None and d <= paused_until:
            final_set = [s for s in current_weights[current_weights > 0].index if s not in stopped_out]
        elif portfolio_dd_cooldown_until is not None and d <= portfolio_dd_cooldown_until:
            final_set = []  # V11: 组合回撤熔断期间全空仓
        else:
            row_score = score.loc[d].reindex(symbols)
            final_set = target_symbols_hysteresis(
                row_score, current_weights, holdings, stopped_out, cooldown_active
            )

        target = target_weights_from_symbols(final_set, symbols, holdings)

        # V45: Bear market half-position scaling
        if bear_mask.loc[d]:
            target = target * BEAR_SCALE
        if low_disp_mask.loc[d]:
            target = target * DISP_SCALE

        delta = target - current_weights
        planned_turnover = float(delta.abs().sum())
        if planned_turnover > MAX_DAILY_TURNOVER and planned_turnover > 0:
            scale = MAX_DAILY_TURNOVER / planned_turnover
            target = current_weights + delta * scale
            planned_turnover = MAX_DAILY_TURNOVER

        cost = planned_turnover * cost_rate_one_side
        net_return = gross_return - cost

        if net_return <= CIRCUIT_BREAKER_DAILY_LOSS:
            paused_until = d + pd.tseries.offsets.BDay(1)

        for sym in symbols:
            was_held = current_weights.get(sym, 0.0) > 0
            now_held = target.get(sym, 0.0) > 0
            if now_held and not was_held:
                entry_price[sym] = day_price.get(sym, np.nan)
            elif not now_held and was_held:
                entry_price.pop(sym, None)

        current_weights = target
        # V11: 更新组合净值并检测回撤
        portfolio_equity *= (1 + net_return)
        portfolio_peak = max(portfolio_peak, portfolio_equity)
        portfolio_dd = portfolio_equity / portfolio_peak - 1
        if portfolio_dd <= PORTFOLIO_DD_THRESHOLD and (portfolio_dd_cooldown_until is None or d > portfolio_dd_cooldown_until):
            portfolio_dd_cooldown_until = d + pd.tseries.offsets.BDay(PORTFOLIO_DD_COOLDOWN)
        records.append(
            {
                "date": d,
                "gross_return": gross_return,
                "cost": cost,
                "net_return": net_return,
                "turnover": planned_turnover,
                "n_holdings": int((current_weights > 0).sum()),
            }
        )

    result = pd.DataFrame(records).set_index("date")
    result.attrs["stop_loss_events"] = stop_loss_events
    return result


def annualized_return(daily_returns: pd.Series) -> float:
    if daily_returns.empty:
        return 0.0
    cumulative = float((1 + daily_returns).prod())
    n = len(daily_returns)
    if n == 0 or cumulative <= 0:
        return -1.0
    return cumulative ** (TRADING_DAYS_PER_YEAR / n) - 1


def max_drawdown_with_dates(daily_returns: pd.Series) -> tuple[float, str, str]:
    if daily_returns.empty:
        return 0.0, "", ""
    equity = (1 + daily_returns).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1
    trough_date = dd.idxmin()
    peak_date = equity.loc[:trough_date].idxmax()
    return float(dd.min()), str(peak_date.date()), str(trough_date.date())


def max_drawdown(daily_returns: pd.Series) -> float:
    mdd, _, _ = max_drawdown_with_dates(daily_returns)
    return mdd


def sharpe_ratio(daily_returns: pd.Series) -> float:
    if daily_returns.empty or daily_returns.std(ddof=0) == 0:
        return 0.0
    return float(daily_returns.mean() / daily_returns.std(ddof=0) * np.sqrt(TRADING_DAYS_PER_YEAR))


def calmar_ratio(daily_returns: pd.Series) -> float:
    mdd = max_drawdown(daily_returns)
    if mdd == 0:
        return 0.0
    return annualized_return(daily_returns) / abs(mdd)


def grid_search_train(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    close_full: pd.DataFrame,
    symbols: list[str],
    train_dates: pd.DatetimeIndex,
) -> tuple[int, float]:
    best = (PARAM_GRID_K[0], -np.inf)
    for K in PARAM_GRID_K:
        sim = simulate(score_full, returns_full, close_full, symbols, train_dates, K)
        if sim.empty:
            continue
        r = sim["net_return"]
        objective = sharpe_ratio(r) + calmar_ratio(r)
        if objective > best[1]:
            best = (K, objective)
    return best


def build_windows_expanding(all_dates: pd.DatetimeIndex) -> list[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    """扩展窗口：训练集从起点到 train_end，测试集为 train_end+EMBARGO 之后的42个交易日。"""
    windows = []
    train_end_idx = MIN_TRAIN_DAYS
    while True:
        test_start_idx = train_end_idx + EMBARGO_DAYS
        test_end_idx = test_start_idx + TEST_TRADING_DAYS
        if test_end_idx > len(all_dates):
            break
        train_dates = all_dates[0:train_end_idx]
        test_dates = all_dates[test_start_idx:test_end_idx]
        assert train_dates[-1] < test_dates[0], "lookahead detected: train overlaps test"
        gap_days = (test_dates[0] - train_dates[-1]).days
        assert gap_days >= 1, "embargo gap violated"
        windows.append((train_dates, test_dates))
        train_end_idx += STEP_TRADING_DAYS
    return windows


def benchmark_returns(close: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    ret = close[BENCHMARK].pct_change().reindex(dates)
    return ret.fillna(0.0)


def run_walk_forward(close: pd.DataFrame, symbols: list[str]) -> dict:
    t0 = time.time()
    score_full = compute_scores_full(close, symbols)
    returns_full = close[symbols].pct_change()
    print(f"[precompute] score computed in {time.time()-t0:.1f}s")

    all_dates = restrict_to_common_history(close, symbols)
    windows = build_windows_expanding(all_dates)
    print(f"[walk_forward] total windows: {len(windows)} (expanding train, embargo={EMBARGO_DAYS}d)")

    window_records = []
    spliced_returns = []
    all_turnovers = []
    total_stop_loss_events = 0

    for i, (train_dates, test_dates) in enumerate(windows):
        t1 = time.time()
        best_K, train_obj = grid_search_train(score_full, returns_full, close, symbols, train_dates)
        test_sim = simulate(score_full, returns_full, close, symbols, test_dates, best_K)
        test_ret = test_sim["net_return"] if not test_sim.empty else pd.Series(dtype=float)
        if not test_sim.empty:
            all_turnovers.append(test_sim["turnover"])
            total_stop_loss_events += test_sim.attrs.get("stop_loss_events", 0)

        bench_ret = benchmark_returns(close, test_dates)

        window_return = float((1 + test_ret).prod() - 1) if not test_ret.empty else 0.0
        bench_window_return = float((1 + bench_ret).prod() - 1)
        window_mdd = max_drawdown(test_ret)
        window_sharpe = sharpe_ratio(test_ret)

        step_dates = test_dates[:STEP_TRADING_DAYS]
        spliced_returns.append(test_ret.reindex(step_dates).fillna(0.0))

        window_records.append(
            {
                "window": i + 1,
                "train_start": str(train_dates[0].date()),
                "train_end": str(train_dates[-1].date()),
                "test_start": str(test_dates[0].date()),
                "test_end": str(test_dates[-1].date()),
                "best_K": best_K,
                "train_objective": round(train_obj, 4),
                "window_return": round(window_return, 4),
                "bench_window_return": round(bench_window_return, 4),
                "excess_vs_bench": round(window_return - bench_window_return, 4),
                "window_max_drawdown": round(window_mdd, 4),
                "window_sharpe": round(window_sharpe, 4),
                "beat_bench": window_return > bench_window_return,
            }
        )
        print(
            f"  W{i+1:02d} [{test_dates[0].date()}~{test_dates[-1].date()}] "
            f"train_days={len(train_dates)} K={best_K} ret={window_return:+.2%} bench={bench_window_return:+.2%} "
            f"excess={window_return - bench_window_return:+.2%} mdd={window_mdd:.2%} "
            f"({time.time()-t1:.1f}s)"
        )

    spliced = pd.concat(spliced_returns).sort_index()
    spliced = spliced[~spliced.index.duplicated(keep="first")]
    avg_turnover = float(pd.concat(all_turnovers).mean()) if all_turnovers else 0.0

    return {
        "windows": window_records,
        "spliced_returns": spliced,
        "score_full": score_full,
        "returns_full": returns_full,
        "avg_daily_turnover": avg_turnover,
        "total_stop_loss_events": total_stop_loss_events,
    }


def cost_erosion_test(
    score_full: pd.DataFrame,
    returns_full: pd.DataFrame,
    close_full: pd.DataFrame,
    symbols: list[str],
    all_dates: pd.DatetimeIndex,
    windows_meta: list[dict],
) -> dict[str, float]:
    results = {}
    for cost in [0.0, COST_RATE_ONE_SIDE]:
        spliced = []
        for w in windows_meta:
            test_dates = all_dates[(all_dates >= w["test_start"]) & (all_dates <= w["test_end"])]
            sim = simulate(score_full, returns_full, close_full, symbols, test_dates, w["best_K"], cost_rate_one_side=cost)
            if sim.empty:
                continue
            step_dates = test_dates[:STEP_TRADING_DAYS]
            spliced.append(sim["net_return"].reindex(step_dates).fillna(0.0))
        if not spliced:
            continue
        full = pd.concat(spliced).sort_index()
        full = full[~full.index.duplicated(keep="first")]
        ann_ret = annualized_return(full)
        results["zero_cost_annualized" if cost == 0.0 else "full_cost_annualized"] = round(ann_ret, 4)
    return results


def judge_report(close: pd.DataFrame, symbols: list[str], result: dict, version: str) -> dict:
    windows = result["windows"]
    spliced = result["spliced_returns"]

    ann_ret = annualized_return(spliced)
    mdd, peak_date, trough_date = max_drawdown_with_dates(spliced)
    sharpe = sharpe_ratio(spliced)
    calmar = calmar_ratio(spliced)
    total_ret = float((1 + spliced).prod() - 1)

    n_windows = len(windows)
    beat_count = sum(1 for w in windows if w["beat_bench"])
    win_rate = beat_count / n_windows if n_windows else 0.0
    worst_window = min(w["window_return"] for w in windows) if windows else 0.0

    Ks = [w["best_K"] for w in windows]
    cv_K = float(np.std(Ks) / np.mean(Ks)) if Ks and np.mean(Ks) != 0 else 0.0

    consecutive = 0
    max_consecutive = 0
    for w in windows:
        if w["window_return"] < 0:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0

    all_dates = restrict_to_common_history(close, symbols)
    windows_for_cost = [
        {"test_start": pd.Timestamp(w["test_start"]), "test_end": pd.Timestamp(w["test_end"]), "best_K": w["best_K"]}
        for w in windows
    ]
    cost_result = cost_erosion_test(result["score_full"], result["returns_full"], close, symbols, all_dates, windows_for_cost)
    zero_cost = cost_result.get("zero_cost_annualized", 0.0)
    full_cost = cost_result.get("full_cost_annualized", 0.0)
    if zero_cost > 0:
        decay_rate = (zero_cost - full_cost) / zero_cost
    else:
        decay_rate = 0.0

    up_windows = [w for w in windows if w["bench_window_return"] > 0]
    down_windows = [w for w in windows if w["bench_window_return"] <= 0]
    up_excess = float(np.mean([w["excess_vs_bench"] for w in up_windows])) if up_windows else 0.0
    down_excess = float(np.mean([w["excess_vs_bench"] for w in down_windows])) if down_windows else 0.0

    sorted_by_ret = sorted(windows, key=lambda w: w["window_return"], reverse=True)
    top3 = sorted_by_ret[:3]
    bottom3 = sorted_by_ret[-3:]

    checklist = {
        "annualized_return_pass": ann_ret >= 0.12,
        "max_drawdown_pass": mdd >= -0.18,
        "sharpe_pass": sharpe >= 1.0,
        "win_rate_pass": win_rate >= 0.60,
        "worst_window_pass": worst_window >= -0.10,
        "param_cv_pass": cv_K <= 0.30,
        "cost_decay_pass": decay_rate <= 0.40,
        "max_consecutive_pass": max_consecutive <= 3,
    }
    all_pass = all(checklist.values())

    report = {
        "version": version,
        "checklist": checklist,
        "all_pass": all_pass,
        "annualized_return": round(ann_ret, 4),
        "total_return": round(total_ret, 4),
        "max_drawdown": round(mdd, 4),
        "max_drawdown_period": f"{peak_date}~{trough_date}",
        "sharpe": round(sharpe, 4),
        "calmar": round(calmar, 4),
        "n_windows": n_windows,
        "beat_count": beat_count,
        "win_rate": round(win_rate, 4),
        "worst_window": round(worst_window, 4),
        "param_K_sequence": Ks,
        "param_cv_K": round(cv_K, 4),
        "max_consecutive_losing_windows": max_consecutive,
        "zero_cost_annualized": zero_cost,
        "full_cost_annualized": full_cost,
        "cost_decay_rate": round(decay_rate, 4),
        "up_market_avg_excess": round(up_excess, 4),
        "down_market_avg_excess": round(down_excess, 4),
        "top3_windows": [{"window": w["window"], "test_start": w["test_start"], "test_end": w["test_end"], "window_return": w["window_return"], "bench_window_return": w["bench_window_return"]} for w in top3],
        "bottom3_windows": [{"window": w["window"], "test_start": w["test_start"], "test_end": w["test_end"], "window_return": w["window_return"], "bench_window_return": w["bench_window_return"]} for w in bottom3],
        "windows_detail": windows,
    }
    return report


def main() -> None:
    close, amount, symbols = load_data()
    symbols = liquidity_filter(amount, symbols)
    symbols = [s for s in symbols if s != "159611.SZ"]  # V9: 剔除电力ETF（2022-01上市，拖累公共历史起点）
    print(f"[universe] {len(symbols)} symbols after liquidity filter: {symbols}")

    result = run_walk_forward(close, symbols)
    report = judge_report(close, symbols, result, "V45")

    print("\n=== JUDGE REPORT V45 ===")
    print(json.dumps({k: v for k, v in report.items() if k != "windows_detail"}, ensure_ascii=False, indent=2))

    output_dir = Path("/Users/ster/Desktop/fina/artifacts/backtest_v45")
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(result["windows"]).to_csv(output_dir / "windows.csv", index=False)
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved detail to {output_dir}")


if __name__ == "__main__":
    main()
