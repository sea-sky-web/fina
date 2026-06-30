# Data Contract

## ETF Basic

Normalized table: `etf_basic`

| Column | Type | Description |
| --- | --- | --- |
| symbol | string | Standard code with exchange suffix, e.g. `510300.SH` |
| code | string | Six-digit ETF code |
| exchange | string | `SH` or `SZ` |
| name | string | ETF short name |
| full_name | string | ETF full name when available |
| index_code | string | Tracked index code when available |
| index_name | string | Tracked index name when available |
| manager | string | Fund manager when available |
| list_date | date | Listing date when available |
| latest_price | double | Latest market price from spot data when available |
| pct_chg | double | Latest percentage change from spot data when available |
| volume | double | Latest trading volume when available |
| amount | double | Latest turnover amount when available |
| status | string | Listing status |
| provider | string | Source provider |
| updated_at | timestamp | Collection or normalization timestamp |

## ETF Daily

Normalized table: `etf_daily`

| Column | Type | Description |
| --- | --- | --- |
| symbol | string | Standard code with exchange suffix |
| date | date | Trading date |
| open | double | Open price |
| high | double | High price |
| low | double | Low price |
| close | double | Close price |
| pre_close | double | Previous close when available |
| change | double | Price change when available |
| pct_chg | double | Percentage change when available |
| volume | double | Trading volume, normalized to shares when possible |
| amount | double | Turnover amount, normalized to CNY when possible |
| factor | double | Adjustment factor; `1.0` if unavailable |
| provider | string | Source provider |
| updated_at | timestamp | Collection or normalization timestamp |

## Data Status

Normalized API model: `data_status`

| Field | Type | Description |
| --- | --- | --- |
| provider | string | Data provider |
| dataset | string | Dataset name |
| last_success_at | timestamp | Last successful collection time |
| last_trade_date | date | Latest trading date in data |
| rows | integer | Row count |
| status | string | `ok`, `stale`, `empty`, or `error` |
| message | string | Human-readable status message |

## ETF Rotation Inputs

Tracked file: `config/etf_rotation_inputs.csv`

This file is intentionally manual in v0.1. It lets the user add industry and theme
research judgement without pretending that the system can automatically infer every
sector's fundamental cycle.

| Column | Type | Description |
| --- | --- | --- |
| symbol | string | Optional ETF symbol override. Empty means the row applies to the theme. |
| theme | string | Theme bucket, e.g. `半导体芯片`, `科技AI`, `新能源` |
| etf_type | string | `行业`, `主题`, `风格`, `宽基`, `货币债券`, or `其他` |
| boom_status | string | Manual cycle label: `上行`, `震荡`, `下行`, or `不确定` |
| boom_score | double | Manual industry/theme cycle score from 0 to 100 |
| valuation_percentile | double | Manual valuation percentile from 0 to 100; lower is cheaper |
| structure_score | double | Manual ETF structure quality score from 0 to 100 |
| notes | string | Research notes shown in the daily report |

## ETF Rotation Radar

API endpoint: `GET /api/rotation/report?top_n=10`

Job entry point: `python -m app.jobs.daily_signal`

The v0.1 radar combines manual boom/valuation inputs with daily price and turnover data.
Weights:

| Module | Weight |
| --- | ---: |
| 行业景气 | 30% |
| 动量趋势 | 25% |
| 估值赔率 | 15% |
| ETF 结构质量 | 10% |
| 流动性 | 10% |
| 风险/拥挤度 | 10% |

Output fields in `daily-signal.json`:

| Field | Type | Description |
| --- | --- | --- |
| radar_date | date | Latest local trading date used by the radar |
| rankings | array | Top ETF ranking rows |
| pools | object | Symbol lists for `core_candidates`, `watchlist`, and `avoid` |
| notes | array | Data and research caveats |

Ranking row fields:

| Field | Type | Description |
| --- | --- | --- |
| total_score | double | Weighted 0-100 score |
| boom_score | double | Manual cycle score |
| momentum_score | double | Relative return, moving-average, and turnover-growth score |
| valuation_score | double | `100 - valuation_percentile` |
| structure_score | double | Manual ETF structure quality score |
| liquidity_score | double | Cross-sectional 20-day turnover score |
| risk_score | double | Volatility/drawdown/overheat risk score, higher is safer |
| state | string | Interpretable state label such as `景气上行 + 动量确认` |
| action | string | Research action label such as `主线候选`, `左侧观察`, or `暂不优先` |

## ETF Factors

Normalized table: `factors`

| Column | Type | Description |
| --- | --- | --- |
| symbol | string | Standard ETF symbol |
| date | date | Factor observation date |
| factor_name | string | Factor identifier, e.g. `momentum_60d` |
| factor_value | double | Numeric factor value computed only from data up to `date` |
| rank | integer | Cross-sectional rank on the same `date`; `1` is the highest value |
| percentile | double | Cross-sectional percentile on the same `date`, from 0 to 1 |
| lookback_days | integer | Rolling lookback window used by the factor |
| provider | string | Factor data provider, usually `local` |
| updated_at | timestamp | Factor rebuild timestamp |

Current factor definitions:

| Factor | Definition |
| --- | --- |
| momentum_60d | `close_today / close_60_trading_days_ago - 1` |
| volatility_30d | `std(log_return) * sqrt(252)` over a 30-trading-day window |
| turnover_20d | 20-trading-day rolling average of turnover amount |
| max_drawdown_60d | Worst drawdown over a 60-trading-day rolling window |
| risk_adjusted_return_60d | 60-day momentum divided by 30-day annualized volatility |
| liquidity_stability_20d | 20-day average turnover amount divided by turnover standard deviation |
| trend_strength_20_60d | 20-day moving average divided by 60-day moving average minus 1 |

Factor definitions API also includes:

| Field | Type | Description |
| --- | --- | --- |
| direction | string | `higher_better` or `lower_better`; determines favorable rank direction |
| category | string | `return`, `risk`, `liquidity`, or `trend` |
| format | string | `percent`, `amount`, or `ratio` |
| interpretation | string | Chinese explanation for research UI display |

## Research Signals

API models: `ResearchSignal`, `SignalComponent`, and `SignalExplanation`.

Research signals are historical research explanations, not trading instructions.

| Field | Type | Description |
| --- | --- | --- |
| symbol | string | Standard ETF symbol |
| name | string | ETF display name |
| theme | string | Inferred ETF theme |
| date | date | Signal observation date |
| research_score | double | Transparent weighted score from 0 to 100 |
| priority | string | Research attention label, such as `观察优先级高` |
| components | array | Weighted factor components used in the score |
| explanation | object | Observation reasons, risk notes, validation notes, and data notes |
| provider | string | Usually `local` |
| updated_at | timestamp | Factor rebuild timestamp |

Signal component fields:

| Field | Type | Description |
| --- | --- | --- |
| factor_name | string | Factor identifier |
| label | string | Display label |
| category | string | Factor category |
| direction | string | Favorable direction |
| value_format | string | Display format |
| factor_value | double | Raw factor value |
| rank | integer | Favorable cross-sectional rank; `1` is best |
| percentile | double | Favorable percentile from 0 to 1 |
| weight | double | Fixed score weight |
| contribution | double | Point contribution to `research_score` |
| interpretation | string | Human-readable factor explanation |

## Factor Diagnostics

API model: `FactorDiagnostics`.

Endpoint:

```text
GET /api/factors/diagnostics?name=momentum_60d&horizon=20&limit=10
```

Factor diagnostics are historical research diagnostics, not trading instructions.

| Field | Type | Description |
| --- | --- | --- |
| factor_name | string | Factor identifier |
| date | date | Diagnostic observation date |
| definition | object | Factor definition, direction, format, interpretation, and limitation |
| distribution | object | Current cross-sectional count, missing count, min, quartiles, max, and mean |
| top | array | Current most favorable ETF rows by factor rank |
| bottom | array | Current least favorable ETF rows by factor rank |
| forward_return | object | Historical Top 20% vs Bottom 20% future-return sample diagnostic |
| stability | object | Recent rank-change diagnostic |
| data_notes | array | Research caveats and data notes |
