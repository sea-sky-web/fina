# ETF Rotation Radar Design

## Positioning

This project is an industry/theme ETF rotation radar, not a price prediction tool.
It combines observable market data with explicitly maintained research judgement and
turns them into a daily decision-support report.

## Inputs

v0.1 uses five input groups, with only the reliable subset automated today:

| Input group | Current fields | Purpose |
| --- | --- | --- |
| ETF basic info | `symbol`, `name`, `index_name`, inferred `theme` | Define the analysis object |
| Price and trading data | `close`, `amount` | Momentum, liquidity, volatility, drawdown |
| Valuation input | Manual `valuation_percentile` | Estimate odds and crowding risk |
| ETF structure input | Manual `structure_score` | Reflect size, concentration, fee, tracking quality when known |
| Cycle input | Manual `boom_status`, `boom_score`, `notes` | Reflect industry/theme cycle direction |

Manual fields live in:

```text
config/etf_rotation_inputs.csv
```

Missing manual fields default to neutral scores. This is intentional: unknown data
should not be converted into a fake positive or negative signal.

## Processing

### Classification

The service infers:

- `theme`: 半导体芯片, 科技AI, 医药医疗, 金融地产, 新能源, 资源能源, 消费, 红利低波, 宽基指数, 科创创业, 港股中概, 海外指数, 货币现金, or 其他
- `etf_type`: 行业, 主题, 风格, 宽基, 货币债券, or 其他

### Momentum

The radar calculates:

- 1-month, 3-month, and 6-month return
- 1-month, 3-month, and 6-month relative return versus `510300.SH`
- 20-day, 60-day, and 120-day moving-average status
- 20-day amount growth

### Valuation

Manual `valuation_percentile` is converted into:

```text
valuation_score = 100 - valuation_percentile
```

Low percentile means better odds. High percentile is a risk constraint, not a hard
sell label.

### Cycle

v0.1 keeps industry cycle judgement manual:

- `boom_status`: 上行, 震荡, 下行, or 不确定
- `boom_score`: 0 to 100

This avoids brittle automatic news interpretation before data sources are stable.

### Structure, Liquidity, and Risk

The radar also scores:

- ETF structure quality from manual input
- liquidity from cross-sectional 20-day amount
- risk from 20-day volatility, 60-day drawdown, and overheating penalty

### Composite Score

```text
total_score =
0.30 * boom_score +
0.25 * momentum_score +
0.15 * valuation_score +
0.10 * structure_score +
0.10 * liquidity_score +
0.10 * risk_score
```

## Outputs

### Ranking

Each ranked ETF includes:

- symbol, name, theme, ETF type
- total score and score breakdown
- boom status and valuation percentile
- state label
- research action label
- returns, drivers, risk notes, and manual input note

### State Labels

| State | Meaning | Action label |
| --- | --- | --- |
| 景气上行 + 动量确认 | Cycle and price action agree | 主线候选 |
| 景气上行 + 动量未确认 | Fundamentals improving, price not confirmed | 左侧观察 |
| 动量强 + 景气弱 | Price action may be flow-driven | 谨慎观察 |
| 低估值 + 景气下行 | Cheap but weak cycle | 价值陷阱 |
| 高估值 + 高拥挤 | Expensive and risk score weak | 控仓/回避追高 |
| 景气改善 + 动量改善 | Early improvement | 重点跟踪 |
| 景气/动量均弱 | Weak cycle and price | 暂不优先 |
| 中性震荡 | No strong conclusion | 继续观察 |

### Pools

- `core_candidates`: 主线候选 and 重点跟踪
- `watchlist`: 左侧观察, 谨慎观察, and 继续观察
- `avoid`: 价值陷阱, 控仓/回避追高, and 暂不优先

## Report Channel

Daily automation runs:

```bash
PYTHONPATH=backend python -m app.jobs.daily_signal \
  --limit 100 \
  --lookback-days 365 \
  --top-n 10 \
  --output-md artifacts/daily-signal.md \
  --output-json artifacts/daily-signal.json
```

GitHub Actions creates a GitHub Issue whose body is the full markdown report.

## Research Boundary

The report may say “观察”, “重点跟踪”, “控仓”, or “暂不优先”. It should not say
“买入”, “卖出”, “目标价”, or anything that implies guaranteed return or automated
execution.
