"""Layer 3 验证: 事件驱动独立回测 — 完全独立于 engine.py 的实现."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StrategyConfig, DEFAULT_CONFIG


def bt_simulate(
    score_full: pd.DataFrame,
    close: pd.DataFrame,
    symbols: list[str],
    k_schedule: list[dict],
    config: StrategyConfig = DEFAULT_CONFIG,
) -> pd.Series:
    """事件驱动独立模拟.

    完整实现止损/冷却/熔断/组合回撤保护/再入场,
    代码结构刻意与 engine.py 不同以实现真正的交叉验证.
    """
    bench_px = close[config.benchmark]
    bench_ret = bench_px.pct_change().fillna(0.0)
    bench_short_ma = bench_px.rolling(10).mean()
    bench_long_ma = bench_px.rolling(30).mean()

    asset_returns = close[symbols].pct_change()

    # 状态变量
    portfolio = {s: 0.0 for s in symbols}
    portfolio[config.benchmark] = 0.0
    buy_price = {}
    cd_expire = {}
    freeze_until = None
    nav = 1.0
    nav_high = 1.0
    dd_freeze_until = None
    up_streak = 0
    reenter_bench_until = None

    sl_count = 0
    re_count = 0
    output = []

    for win in k_schedule:
        t0 = pd.Timestamp(win["test_start"])
        t1 = pd.Timestamp(win["test_end"])
        K = win["best_K"]
        step_n = win.get("step_days", config.step_trading_days)

        idx = close.index[(close.index >= t0) & (close.index <= t1)]
        idx = idx[:step_n]

        for day in idx:
            px_today = close.loc[day].reindex(symbols)
            ret_today = asset_returns.loc[day].reindex(symbols).fillna(0.0)
            br = float(bench_ret.loc[day])

            # 持仓日收益
            pnl = sum(portfolio.get(s, 0.0) * float(ret_today.get(s, 0.0)) for s in symbols)
            pnl += portfolio.get(config.benchmark, 0.0) * br

            # 连涨计数
            if br > 0:
                up_streak += 1
            else:
                up_streak = 0

            # 冷却池
            active_cd = {s for s, exp in cd_expire.items() if exp >= day}

            # 止损检查
            stopped = set()
            for s in symbols:
                if portfolio.get(s, 0.0) <= 0:
                    continue
                ep = buy_price.get(s)
                cpx = px_today.get(s)
                if ep is None or pd.isna(cpx) or ep == 0:
                    continue
                drawdown = cpx / ep - 1
                if drawdown <= config.stop_loss_threshold:
                    stopped.add(s)
                    cd_expire[s] = day + pd.tseries.offsets.BDay(config.cooldown_days)
                    sl_count += 1

            # 组合回撤保护
            in_dd_freeze = dd_freeze_until is not None and day <= dd_freeze_until
            if in_dd_freeze:
                can_reenter = (
                    br >= config.reentry_bench_spike
                    or up_streak >= config.reentry_consecutive_up
                )
                if can_reenter:
                    dd_freeze_until = None
                    in_dd_freeze = False
                    re_count += 1
                    reenter_bench_until = day + pd.tseries.offsets.BDay(
                        config.reentry_bench_days
                    )
                    nav_high = nav * (1 + config.reentry_peak_buffer)

            add_bench = reenter_bench_until is not None and day <= reenter_bench_until

            # 选股
            if freeze_until is not None and day <= freeze_until:
                picks = [
                    s for s in symbols
                    if portfolio.get(s, 0.0) > 0
                    and s not in stopped
                ]
            elif in_dd_freeze:
                picks = []
                add_bench = False
            else:
                day_score = score_full.loc[day].reindex(symbols) if day in score_full.index else pd.Series(dtype=float)
                pos_scores = day_score.dropna()
                pos_scores = pos_scores[pos_scores > 0].sort_values(ascending=False)
                pos_scores = pos_scores[~pos_scores.index.isin(active_cd)]

                slots = max(K - 1, 1) if add_bench else K

                # 迟滞逻辑
                held = {s for s in symbols if portfolio.get(s, 0.0) > 0 and s not in stopped}
                top_pool = set(pos_scores.head(slots + config.hysteresis_buffer).index)
                keepers = held & top_pool
                keep_ranked = pos_scores[pos_scores.index.isin(keepers)]
                keep_list = list(keep_ranked.head(slots).index)

                remaining = slots - len(keep_list)
                newcomers = [s for s in pos_scores.index if s not in keep_list]
                picks = keep_list + newcomers[:max(remaining, 0)]

            # 目标权重
            new_w = {s: 0.0 for s in symbols}
            new_w[config.benchmark] = 0.0
            if add_bench and picks:
                n = len(picks) + 1
                pw = min(1.0 / n, config.max_symbol_weight)
                new_w[config.benchmark] = pw
                for s in picks:
                    new_w[s] = pw
            elif picks:
                pw = min(1.0 / len(picks), config.max_symbol_weight)
                for s in picks:
                    new_w[s] = pw

            # 牛熊缩放
            is_bear = False
            sma = bench_short_ma.get(day)
            lma = bench_long_ma.get(day)
            if sma is not None and lma is not None and not (pd.isna(sma) or pd.isna(lma)):
                is_bear = float(sma) < float(lma)
            mult = config.bear_scale if is_bear else config.bull_boost
            for s in new_w:
                new_w[s] *= mult

            # 换手限制
            delta_abs = sum(abs(new_w.get(s, 0.0) - portfolio.get(s, 0.0)) for s in set(list(new_w) + list(portfolio)))
            if delta_abs > config.max_daily_turnover and delta_abs > 0:
                ratio = config.max_daily_turnover / delta_abs
                for s in new_w:
                    new_w[s] = portfolio.get(s, 0.0) + (new_w[s] - portfolio.get(s, 0.0)) * ratio
                delta_abs = config.max_daily_turnover

            cost = delta_abs * config.cost_rate_one_side
            net = pnl - cost

            # 熔断
            if net <= config.circuit_breaker_daily_loss:
                freeze_until = day + pd.tseries.offsets.BDay(1)

            # 更新入场价
            for s in symbols:
                was_in = portfolio.get(s, 0.0) > 0
                now_in = new_w.get(s, 0.0) > 0
                if now_in and not was_in:
                    buy_price[s] = px_today.get(s, np.nan)
                elif not now_in and was_in:
                    buy_price.pop(s, None)

            portfolio = dict(new_w)
            nav *= (1 + net)
            nav_high = max(nav_high, nav)
            dd = nav / nav_high - 1
            if dd <= config.portfolio_dd_threshold and (
                dd_freeze_until is None or day > dd_freeze_until
            ):
                dd_freeze_until = day + pd.tseries.offsets.BDay(config.portfolio_dd_cooldown)

            output.append({"date": day, "net_return": net})

    if not output:
        return pd.Series(dtype=float)

    ret_s = pd.DataFrame(output).set_index("date")["net_return"]
    ret_s = ret_s[~ret_s.index.duplicated(keep="first")]
    ret_s.attrs["stop_loss_events"] = sl_count
    ret_s.attrs["reentry_events"] = re_count
    return ret_s.sort_index()
