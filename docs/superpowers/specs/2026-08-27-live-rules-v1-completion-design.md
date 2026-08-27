# live-rules-v1 完成方案：backtrader 回测 + 4 段切片验证

**日期**：2026-08-27
**作者**：弓长超
**范围**：在 `experiment/live-rules-v1` 分支当前 620 行实盘信号 CLI 基础上，补齐回测执行器，用历史数据验证"20 日动量 + 20 日均线 + 流动性门槛"规则在含手续费的前提下能否持续跑赢现金基准且回撤可控。

## 1. 背景与目标

### 1.1 当前状态

分支上已完成 live-rules-v1 实盘信号 CLI（提交 `7742ae6`）：

- `backend/app/signal_rule.py`：20 日动量排名 + 20 日均线趋势确认 + 流动性门槛（5 千万日均成交）+ 主题去重
- `backend/app/portfolio_state.py`：3 持仓位、16% 止损、2% 动量差换仓阈值、5 元/笔手续费建模
- `backend/app/market_data.py`：AKShare 实时行情直取（新浪源，不落盘）
- `backend/app/jobs/live_signal.py`：实盘入口，每次现场拉数据输出买卖建议

规则本身**没有可调超参数**，所有常量都写在模块顶部（`MOMENTUM_LOOKBACK_DAYS=20`、`TREND_MA_DAYS=20`、`STOP_LOSS_PCT=0.16` 等）。

### 1.2 缺失

- **回测执行器**：没有任何代码能用历史数据重放 `decide()` 输出净值曲线和绩效指标
- **单元/冒烟测试**：`backend/tests/` 目录为空
- **回测历史缓存**：`scripts/fetch_backtest_history.py` 已写好但没运行，`data/backtest_cache/` 不存在
- **510300 对照基准**：fetch 脚本没拉沪深300 ETF

### 1.3 验收目标

让 v1 规则能在含手续费的前提下，被历史数据证明"比拿现金强、比大盘回撤可控"。具体数值标准见 §6。

## 2. 非目标

明确**不做**，避免范围蔓延：

- 不做 WFO 滚动超参优化（v1 无超参可调）
- 不做双周期 z-score、相对强弱、牛熊 regime 切换（这些是 v2 增强项，见 `docs/STRATEGY_REVIEW.md`）
- 不做实盘自动调度（用户决定保持手动运行 `PYTHONPATH=backend python -m app.jobs.live_signal`）
- 不引入 backtrader 以外的第三方回测框架
- 不做 web UI / 前端展示

## 3. 架构决策：backtrader 做账本，decide() 做规则

### 3.1 方案对比（结论）

| 方案 | 结论 |
|---|---|
| A. 逐日重放 `decide()`（纯 Python） | 简单，但交易撮合/佣金要自己写，容易和回测框架不一致 |
| B. 向量化回测 | 要重写规则逻辑，两套实现必然漂移 |
| **C. backtrader 框架 + 桥接 decide()** | **采纳**：backtrader 负责交易撮合/佣金/净值曲线，规则复用现有 `decide()` |

### 3.2 桥接设计

在 backtrader 的 `Strategy.next()`（每个交易日回调）里：

1. 从各 data feed 截取截至当日的 ≤90 日 close/amount 窗口
2. 对每只标的构造 `SymbolMetrics`
3. 调 `filter_universe()` + `rank_candidates()` + `decide(as_of=当日)` 得到 `Decision` 列表
4. 把 `Decision` 翻译成 backtrader 订单（`self.buy()` / `self.close()`）

规则逻辑**只有一份**（不重写止损/换仓判断），backtrader 提供成交撮合、逐笔 5 元佣金、逐日权益曲线、交易记录。

### 3.3 数据源约束

新浪接口只返回 close 和 amount，没有独立的 OHLC。backtrader 的 `PandasData` 用 close 字段同时填充 OHLC 四个价格——与"按当日收盘价成交"的假设自洽。报告中注明这一假设。

## 4. 文件改动

| 文件 | 类型 | 职责 |
|---|---|---|
| `backend/app/bt_strategy.py` | **新** | backtrader `Strategy` 子类：窗口→`SymbolMetrics`→`decide()`→订单；持仓状态用内存 `PortfolioState`，不写磁盘 |
| `backend/app/jobs/backtest.py` | **新** | CLI：`PYTHONPATH=backend python -m app.jobs.backtest`。读 parquet → 组装 Cerebro（30000 资金、5 元佣金、close-as-OHLC feeds）→ 跑回测 → 算指标 → 输出 `artifacts/backtest_v1/{report.md, report.json, windows.csv, trades.csv}` |
| `scripts/fetch_backtest_history.py` | **改** | 标的池额外加入 `510300`（沪深300ETF）作买入持有对照 |
| `backend/pyproject.toml` | **改** | 新增可选依赖组 `backtest = ["backtrader>=1.9.78"]`；实盘信号路径不背此依赖 |
| `backend/tests/test_metrics.py` | **新** | 用固定收益率序列测 `app/metrics.py` 四个函数的边界值和数值 |
| `backend/tests/test_bt_strategy.py` | **新** | 用**合成的 3 只标的 × 30 个交易日**数据构造 `SymbolMetrics` 序列，断言 `decide()` 输出预期买/卖/止损；冒烟测试用合成数据跑一次 Cerebro 断言有成交 |

不改动：`app/signal_rule.py`、`app/portfolio_state.py`、`app/market_data.py`、`app/report.py`、`app/benchmark.py`、`app/metrics.py`、`app/classify.py`、`app/jobs/live_signal.py`。

## 5. 数据流与执行步骤

### 5.1 完整链路

```
PYTHONPATH=backend python scripts/fetch_backtest_history.py
        ↓
data/backtest_cache/etf_daily.parquet  (含 510300 基准)
        ↓
PYTHONPATH=backend python -m app.jobs.backtest
        ↓
① 读 parquet → 按 symbol 分组并按 date 升序
② 每个 symbol → backtrader.PandasData feed（close 复用为 OHLC）
③ Cerebro：初始资金 30000、固定佣金 5 元/笔
④ Strategy.next() 逐日：
   · 跳过 warmup 期（前 40 个交易日，等动量窗口有数据）
   · 当日各 feed 截取 ≤90 日窗口 → SymbolMetrics
   · filter_universe / rank_candidates → decide(as_of=当日)
   · Decision → broker.order()
⑤ 跑完取 cerebro.getstrategy() 的日度权益曲线 + 交易列表
⑥ app/metrics.py 算指标 → 全段 + 4 段切片
⑦ 510300 买入持有对照
⑧ 写入 artifacts/backtest_v1/{report.md, report.json, windows.csv, trades.csv}
```

### 5.2 4 段非重叠切片（市场周期切片）

| 窗口 | 区间 | 市场特征 |
|---|---|---|
| W1 | 2021-Q3 ~ 2022-Q4 | 熊市 + 筑底 |
| W2 | 2023 全年 | 结构性行情 |
| W3 | 2024 全年 | 剧烈波动 |
| W4 | 2025-Q1 ~ 2026-Q3 | 近期（数据最新） |

每段独立算年化收益 / 最大回撤 / 夏普 / 换手次数 / 止损触发次数，**各自对比现金基准**。`windows.csv` 一行一段。

### 5.3 报告呈现

- `report.md`：全段摘要（年化、回撤、夏普、累计收益）+ 4 行切片表 + 510300 对照行 + 风险提示
- `report.json`：机器可读版，含 `checklist.{annualized_return_pass, max_drawdown_pass, slice_win_count}` 字段
- `windows.csv`：4 行切片原始数字
- `trades.csv`：每笔交易（日期、方向、标的、成交价、手续费、盈亏）

## 6. 验收标准

### 6.1 全段（2021-Q3 ~ 2026-Q3）

- ✅ 年化收益 > 现金基准（取 `app.benchmark.fetch_cash_benchmark()` 当前值，约 2%）
- ✅ 最大回撤 > −25%

### 6.2 4 段切片

- ✅ 至少 3/4 段年化赢现金基准
- ⚠️ 任一段回撤 > −25% 或任一段跑输现金 → 报告中标红 + "可能原因"字段，**不自动判 fail**

### 6.3 对照

- 沪深300 ETF（510300）买入持有仅作**参考**，不作为通过/失败条件

### 6.4 代码质量

- `pytest backend/tests/` 全绿
- `ruff check backend/` 无告警

## 7. 错误处理

| 场景 | 行为 |
|---|---|
| 缓存不存在或空 | CLI 直接 `sys.exit(1)`，stderr 中文提示"请先运行 scripts/fetch_backtest_history.py" |
| 单只 ETF 历史 < 60 日 | 该 symbol 跳过并 stderr 记录，不影响其它 |
| 回测结束零笔交易 | 报告输出"无成交"，指标记 0，附诊断"请检查缓存是否覆盖完整区间" |
| `backtrader` 未安装 | 导入时明确报错并指引 `pip install fina-backend[backtest]` |

## 8. 已知局限（写在报告里的免责声明）

1. **幸存者偏差**：回测标的池是"今日按成交额排序的 ETF"，历史早期这些 ETF 未必存在或流动性足够。`fetch_backtest_history.py` 文件头注释已说明，结论要打折。
2. **OHLC 退化**：新浪数据只有 close，backtrader 用 close 填 OHLC 意味着没有盘中波动，止损/换仓都以收盘价成交——比真实交易更平滑，可能低估回撤。
3. **成交假设**：按当日收盘价瞬时成交，无滑点、无挂单失败。实盘中临近收盘下单通常能接近这个假设，但不完全等价。
4. **单标的小资金**：3 万本金分 3 份，每笔约 1 万，佣金按最低档 5 元/笔，比例约 0.05%——对大资金不具参考性。

## 9. 实施顺序

1. 安装 `backtrader` 依赖（可选依赖组）
2. 运行 `fetch_backtest_history.py`，生成含 510300 的缓存
3. 实现 `app/bt_strategy.py`（Strategy 桥接）
4. 实现 `app/jobs/backtest.py`（CLI 入口）
5. 写 `tests/test_metrics.py` 和 `tests/test_bt_strategy.py`
6. 跑 `python -m app.jobs.backtest`，输出报告到 `artifacts/backtest_v1/`
7. 检查报告指标是否满足 §6 验收标准
8. 如不通过，分析原因后决定调整规则还是放宽阈值
