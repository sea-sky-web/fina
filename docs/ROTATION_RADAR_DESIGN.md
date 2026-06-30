# ETF Rotation Radar Design

## Positioning

This project is an industry/theme ETF rotation radar, not a price prediction tool.
It combines observable market data with explicitly maintained research judgement and
turns them into a daily decision-support report.

## Inputs

v0.2 uses five input groups, with the market-data subset required to come from
production provider responses or explicit cached fallbacks:

| Input group | Current fields | Purpose |
| --- | --- | --- |
| ETF basic info | `symbol`, `name`, `index_name`, inferred `theme` | Define the analysis object |
| Price and trading data | `close`, `amount`, `iopv`, `premium_discount_rate`, `latest_share`, market value fields | Momentum, liquidity, volatility, drawdown, ETF structure checks |
| Valuation input | Manual `valuation_percentile` | Estimate odds and crowding risk |
| ETF structure input | Manual `structure_score` | Reflect size, concentration, fee, tracking quality when known |
| Cycle input | Data-driven cycle proxy plus optional manual `boom_status`, `boom_score`, `notes` | Reflect industry/theme cycle direction |

Manual fields live in:

```text
config/etf_rotation_inputs.csv
```

Missing manual fields default to neutral scores. This is intentional: unknown data
should not be converted into a fake positive or negative signal.

## Data Authenticity

The production system must not use mock, fake, sample, synthetic, or test provider
values for clean ETF market data. `GET /api/data-sources/audit` checks:

- manifest provider and latest collection status
- clean ETF basic and daily row counts
- latest trading date freshness
- provider values in clean market data
- source endpoints such as `fund_etf_spot_em`, `fund_etf_hist_sina`, and
  `fund_etf_hist_em`
- cached fallback usage and missing daily symbols

The daily report includes this audit. Blocking errors make the job fail instead of
silently publishing a report from untrusted data.

## Processing

### Classification

The service infers:

- `theme`: 半导体芯片, 科技AI, 医药医疗, 金融地产, 新能源, 资源能源, 消费, 红利低波, 宽基指数, 科创创业, 港股中概, 海外指数, 货币现金, or 其他
- `etf_type`: 行业, 主题, 风格, 宽基, 货币债券, or 其他

Only `行业` and `主题` enter the rotation radar. `货币债券`, `宽基`, `风格`, and
`其他` are excluded because their risk/return drivers and scoring framework are
different from industry/theme rotation.

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

v0.2 makes the default cycle signal data-driven. It calculates an industry/theme
cycle proxy from same-theme ETF market data:

- 3-month relative strength versus `510300.SH`
- 6-month relative strength versus `510300.SH`
- moving-average status
- 20-day amount growth
- volatility/drawdown risk score

The proxy is primarily theme-level, with a smaller ETF-specific component. If the
manual CSV supplies a non-neutral `boom_score` or explicit `boom_status`, the
manual score is blended in as a correction and the row reports
`boom_source = data+manual`; otherwise `boom_source = data`.

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
