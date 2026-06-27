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
