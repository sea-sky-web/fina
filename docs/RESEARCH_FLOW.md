# ETF Research Flow

本文档回答三个问题：

- 当前系统计算了哪些因子和评分？
- 这些因子、评分经过哪些处理步骤，才形成每日输出？
- 如果已经有持仓，系统如何把候选排序转成加仓、减仓、新增配置或持有不变的研究建议？

本项目只做 ETF 研究解释，不做自动下单，也不输出确定性的投资结论。

## 1. 输入数据

主要输入来自本地 clean 数据和人工维护 CSV。

| 输入 | 位置 | 用途 |
| --- | --- | --- |
| ETF 基础信息 | `data/clean/etf_basic.parquet` | 代码、名称、跟踪指数、主题识别 |
| ETF 日线 | `data/clean/etf_daily.parquet` | 收盘价、成交额、收益、波动、回撤、流动性 |
| 轮动人工输入 | `config/etf_rotation_inputs.csv` | 估值分位、结构质量、可选景气修正 |
| 当前持仓 | API 请求或 `daily_signal --holdings-file` | 当前组合权重，用于生成调整研究建议 |

数据进入研究链路前，需要先完成采集、清洗和数据源审计。日线至少需要
`symbol`, `date`, `close`，最好有 `amount`，否则流动性相关分数只能降级处理。

## 2. 当前因子池

因子由 `backend/app/factors/` 定义，重建入口是：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.jobs.rebuild_factors
```

| 因子 | 公式 | 有利方向 | 含义 |
| --- | --- | --- | --- |
| `momentum_60d` | `close_today / close_60_days_ago - 1` | 越高越好 | 近 60 个交易日价格动量 |
| `volatility_30d` | `std(log_return, 30d) * sqrt(252)` | 越低越好 | 近 30 日年化历史波动率 |
| `turnover_20d` | `mean(amount, 20d)` | 越高越好 | 近 20 日平均成交额 |
| `max_drawdown_60d` | 近 60 日滚动最大回撤 | 越接近 0 越好 | 近期尾部回撤压力 |
| `risk_adjusted_return_60d` | `momentum_60d / volatility_30d` | 越高越好 | 单位波动对应的趋势收益 |
| `liquidity_stability_20d` | `mean(amount, 20d) / std(amount, 20d)` | 越高越好 | 成交额是否稳定、连续 |
| `trend_strength_20_60d` | `MA20 / MA60 - 1` | 越高越好 | 中短期趋势强度 |

## 3. 因子处理步骤

每个交易日、每个 ETF 会先计算原始因子值，再进入处理链路：

1. 原始计算：只使用当前日期及以前的数据，避免未来函数。
2. 异常值处理：默认使用 MAD 方法压制极端值。
3. 标准化：默认把不同量纲的因子转成可比较的标准分。
4. 主题中性化：默认在主题内部做排名，降低宽基、风格、行业结构差异对横截面比较的污染。
5. 排名和分位：生成 `rank` 和 `percentile`，`percentile` 表示该因子在当日横截面的有利分位。
6. 落盘：原始因子写入 `factors.parquet`，处理后因子写入 `factors_processed.parquet`。

研究信号优先读取处理后因子。如果处理后因子缺失，会回退到原始因子。

## 4. 研究信号评分

研究信号由 `backend/app/services/signal_service.py` 生成，对应接口：

```text
GET /api/signals
GET /api/signals/{symbol}
```

信号分数使用因子有利分位和权重计算：

```text
component_score = factor_percentile * factor_weight / available_weight * 100
research_score = sum(component_score)
```

默认备用权重为：

| 因子 | 权重 |
| --- | ---: |
| `momentum_60d` | 25% |
| `risk_adjusted_return_60d` | 25% |
| `trend_strength_20_60d` | 20% |
| `liquidity_stability_20d` | 15% |
| `volatility_30d` | 10% |
| `max_drawdown_60d` | 5% |

如果历史样本足够，系统会用 ICIR 和相关性惩罚生成动态权重。市场状态还会二次调整权重：

- 防御状态：提高低波动、低回撤和流动性稳定权重。
- 风险偏好状态：提高动量、趋势和风险调整收益权重。
- 中性状态：保持基础权重。

输出会包含优势因子、风险提示、验证提示和数据说明。

## 5. 行业/主题轮动雷达

轮动雷达由 `backend/app/services/rotation_service.py` 生成，对应接口：

```text
GET /api/rotation/report?top_n=10
```

雷达只比较 `行业` 和 `主题` ETF。`货币债券`、`宽基`、`风格`、`其他` 不进入同一排名池，因为分析框架不同。

综合分由六个模块组成：

| 模块 | 权重 | 计算来源 |
| --- | ---: | --- |
| 行业景气 | 30% | 同主题市场代理分，可被人工景气输入小幅修正 |
| 动量趋势 | 25% | 1/3/6 月相对收益、均线状态、成交额增长 |
| 估值赔率 | 15% | `100 - valuation_percentile` |
| ETF 结构质量 | 10% | 人工维护结构分 |
| 流动性 | 10% | 20 日成交额横截面分位 |
| 风险/拥挤度 | 10% | 波动、回撤和过热惩罚 |

景气代理分不是新闻/NLP 分数，而是同主题市场数据生成：

```text
individual_boom_proxy =
  35% * 3m_relative_strength_score
+ 20% * 6m_relative_strength_score
+ 20% * moving_average_score
+ 15% * amount_growth_score
+ 10% * risk_score

final_boom_score =
  proxy_score                         if no manual override
  75% * proxy_score + 25% * manual    if manual boom input exists
```

状态和研究动作来自景气、动量、估值和风险组合。例如：

| 状态 | 研究动作 |
| --- | --- |
| 景气上行 + 动量确认 | 主线候选 |
| 景气改善 + 动量改善 | 重点跟踪 |
| 景气上行 + 动量未确认 | 左侧观察 |
| 动量强 + 景气弱 | 谨慎观察 |
| 低估值 + 景气下行 | 价值陷阱 |
| 高估值 + 高拥挤 | 控仓/回避追高 |
| 景气/动量均弱 | 暂不优先 |

## 6. 持仓调整研究建议

新增组合建议由 `backend/app/services/portfolio_advice_service.py` 生成，对应接口：

```text
POST /api/portfolio/advice
```

请求示例：

```json
{
  "holdings": [
    {"symbol": "159998.SZ", "weight": 0.20},
    {"symbol": "513100.SH", "weight": 0.30}
  ],
  "target_count": 5,
  "universe_limit": 50,
  "min_trade_weight": 0.03
}
```

处理步骤：

1. 读取当前持仓权重，权重使用组合小数，例如 `0.20` 表示 20%。
2. 读取当前轮动雷达前 `universe_limit` 名。
3. 只从 `主线候选` 和 `重点跟踪` 中选择前 `target_count` 个目标标的。
4. 根据市场状态设置目标风险暴露：
   - 风险偏好：约 95%
   - 中性：约 75%
   - 防御：约 45%
5. 对目标组合施加风险约束：
   - 单只 ETF 默认不超过 30%
   - 单主题默认不超过 55%
   - 高相关 ETF 簇默认不超过 65%
6. 对比当前权重和目标权重，得到 `delta_weight`。
7. 按 `min_trade_weight` 阈值输出动作标签。

动作标签含义：

| 标签 | 触发条件 | 含义 |
| --- | --- | --- |
| 新增配置候选 | 当前未持有，目标权重大于 0 | 目标组合新增了该标的 |
| 加仓候选 | 目标权重高于当前权重，且差值超过阈值 | 当前配置低于研究目标 |
| 减仓候选 | 当前权重高于目标权重，且差值超过阈值 | 当前配置高于研究目标 |
| 持有不变 | 权重差异未超过阈值 | 暂无明显调整差异 |

这些标签只表示研究模型相对当前组合的差异，不构成实盘下单指令。

## 7. 每日报告输出

基础报告命令：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.jobs.daily_signal \
  --limit 100 \
  --lookback-days 365 \
  --top-n 10 \
  --output-md artifacts/daily-signal.md \
  --output-json artifacts/daily-signal.json
```

## 8. 轮动雷达评估闭环

轮动雷达的历史表现评估入口是：

```text
GET /api/evaluation/rotation/pool-forward-returns?top_n=10&horizons=5,10,20
```

该评估不会用当前排名倒推历史。它会在每个月末信号日，基于当时及以前的
clean 日线重算行业/主题轮动池，再观察未来 5/10/20 个交易日的池子平均收益、
正收益率和相对 `510300.SH` 的胜率。

输出包括：

| 字段 | 含义 |
| --- | --- |
| `summaries` | 各状态池在各观察窗口的聚合表现 |
| `observations` | 每个信号日、每个状态池的单次观察结果 |
| `signal_dates` | 参与评估的月末信号日 |
| `data_notes` | 样本覆盖、计算假设和数据限制 |

这个接口用于回答“主线候选是否真的优于观察池和回避池”，后续调权重、阈值和
状态标签时应优先查看这条评估结果。

如果要加入当前持仓建议，可以准备 CSV：

```csv
symbol,weight
159998.SZ,0.20
513100.SH,0.30
```

然后运行：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.jobs.daily_signal \
  --limit 100 \
  --lookback-days 365 \
  --top-n 10 \
  --holdings-file config/current_holdings.csv \
  --portfolio-target-count 5 \
  --min-trade-weight 0.03 \
  --output-md artifacts/daily-signal.md \
  --output-json artifacts/daily-signal.json
```

此时 markdown 和 JSON 会额外包含：

- 当前暴露
- 目标暴露
- 现金/低风险权重
- 估算换手
- 每个持仓或目标标的的当前权重、目标权重、差值和动作标签
- 每个动作的依据说明

## 9. 业绩验证

业绩不是从当前推荐直接推断，而是通过历史回测和信号跟踪验证：

| 模块 | 入口 | 输出 |
| --- | --- | --- |
| 研究信号回测 | `GET /api/backtests/research-signal` | 净值曲线、收益、波动、回撤、换手、持仓快照 |
| 风险管理轮动核心池回测 | `GET /api/backtests/rotation-core?top_n=5&cost_bps=5` | 月末重算纯数据 `core_candidates`、默认 `risk_score >= 60`、组合风险约束、次日成交、扣成本、验证摘要 |
| Walk-forward 验证 | `backend/app/backtest/walk_forward.py` | 训练期选因子、测试期样本外表现 |
| 信号快照跟踪 | `POST /api/signals/snapshot` + `GET /api/signals/performance` | 历史 Top 信号未来收益表现 |
| 因子诊断 | `GET /api/factors/diagnostics` | 因子分布、Top/Bottom 未来收益、排名稳定性 |

回测链路按历史日期重新生成分数和调仓组合，再用下一阶段实际日收益计算组合表现。核心指标包括累计收益、年化收益、年化波动、最大回撤、类似 Sharpe、日胜率、平均换手和最终净值。

因此，最终业绩来自历史日线的可复现计算，而不是来自当前报告的静态排序。

每个回测结果会输出 `validation`：

| 字段 | 含义 |
| --- | --- |
| `status` | `fail`、`research_pass` 或 `production_pass` |
| `excess_return_vs_benchmark` | 相对指定基准的累计超额收益 |
| `excess_return_vs_universe` | 相对 ETF 池等权基准的累计超额收益 |
| `checks` | 跑赢基准、跑赢等权池、风险调整收益、回撤、样本数、样本外验证等门槛 |

`research_pass` 只表示当前本地历史样本中扣成本后跑赢核心基准；它不是生产批准。
`production_pass` 还需要至少 36 次月度调仓、样本外 walk-forward、回撤门槛和数据源审计一起通过。
历史回测默认禁用人工 CSV 输入，避免把当前主观研究判断穿越到过去；日报和当前组合建议仍可使用人工输入作为显式覆盖层。
`rotation-core` 默认使用 `risk_managed=true`：市场状态控制风险暴露，单只/主题/高相关簇限制集中度，无合格标的的月份转为现金。若要只看信号原始强度，可显式传 `risk_managed=false&min_risk_score=0` 作对照。
