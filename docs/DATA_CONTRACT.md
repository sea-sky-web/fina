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
| iopv | double | Real-time IOPV estimate from spot data when available |
| premium_discount_rate | double | Premium/discount rate from spot data when available |
| pct_chg | double | Latest percentage change from spot data when available |
| change | double | Latest price change from spot data when available |
| open | double | Latest spot open price when available |
| high | double | Latest spot high price when available |
| low | double | Latest spot low price when available |
| pre_close | double | Previous close from spot data when available |
| amplitude | double | Spot amplitude when available |
| volume | double | Latest trading volume when available |
| amount | double | Latest turnover amount when available |
| turnover_rate | double | Latest turnover rate when available |
| volume_ratio | double | Latest volume ratio when available |
| latest_share | double | Latest ETF share count from spot data when available |
| circulating_market_value | double | Circulating market value when available |
| total_market_value | double | Total market value when available |
| spot_date | date | Spot quote data date when available |
| quote_updated_at | timestamp | Spot quote timestamp when available |
| status | string | Listing status |
| provider | string | Source provider |
| source_endpoint | string | Provider endpoint, e.g. `fund_etf_spot_em` |
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
| amplitude | double | Daily amplitude when available |
| turnover_rate | double | Daily turnover rate when available |
| factor | double | Adjustment factor; `1.0` if unavailable |
| provider | string | Source provider |
| source_endpoint | string | Provider endpoint, e.g. `fund_etf_hist_sina` or `fund_etf_hist_em` |
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

This file is a manual override layer. The rotation radar now derives the default
industry/theme cycle proxy from market data, while this CSV can still add
valuation, structure quality, and optional research judgement.

| Column | Type | Description |
| --- | --- | --- |
| symbol | string | Optional ETF symbol override. Empty means the row applies to the theme. |
| theme | string | Theme bucket, e.g. `半导体芯片`, `科技AI`, `新能源` |
| etf_type | string | `行业`, `主题`, `风格`, `宽基`, `货币债券`, or `其他`; only `行业` and `主题` enter the rotation radar |
| boom_status | string | Optional manual cycle label: `上行`, `改善`, `震荡`, `下行`, or `不确定` |
| boom_score | double | Optional manual cycle score from 0 to 100, blended as a small correction when provided |
| valuation_percentile | double | Manual valuation percentile from 0 to 100; lower is cheaper |
| structure_score | double | Manual ETF structure quality score from 0 to 100 |
| notes | string | Research notes shown in the daily report |

## Data Source Audit

API endpoint: `GET /api/data-sources/audit`

The audit only checks production clean ETF market data. Test fixtures and mocked
unit-test frames do not count as valid production data.

| Field | Type | Description |
| --- | --- | --- |
| ok | bool | `false` when production data is empty, stale, failed, or uses non-production providers |
| status | string | `ok`, `warning`, or `error` |
| provider | string | Manifest provider, currently expected to be `akshare` |
| manifest_status | string | Last collection status: `ok`, `degraded`, or `error` |
| collected_at | timestamp | Last collection timestamp |
| spot_source | string | Spot data source path, such as `akshare_spot` or cached fallback |
| selected_rows | integer | ETF universe size selected by the collector |
| basic_rows | integer | Clean ETF basic row count |
| daily_rows | integer | Clean ETF daily row count |
| latest_trade_date | date | Latest date in `etf_daily` |
| symbols_total | integer | Number of selected ETF symbols |
| symbols_with_daily | integer | Number of symbols with clean daily bars |
| daily_missing_symbols | array | Selected symbols missing daily bars |
| source_endpoints | array | Provider endpoints observed in clean data or manifest |
| cached_sources | array | Cached fallback sources used in the latest collection |
| warnings | array | Non-blocking data quality caveats |
| errors | array | Blocking data authenticity or freshness errors |

## ETF Rotation Radar

API endpoint: `GET /api/rotation/report?top_n=10`

Job entry point: `python -m app.jobs.daily_signal`

The v0.2 radar only ranks industry and theme ETFs. Money/bond ETFs, broad-base
ETFs, style ETFs, and uncategorized ETFs are excluded because their analysis
framework differs from sector/theme rotation.

The cycle score is data-driven by default. It uses same-theme market proxies from
daily price and trading data: 3-month and 6-month relative strength, moving-average
status, 20-day turnover growth, and risk score. Manual `boom_score` remains
available as an override-style correction, not as the primary source.

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
| boom_score | double | Data-driven cycle proxy score after optional manual correction |
| boom_source | string | `data` or `data+manual` |
| momentum_score | double | Relative return, moving-average, and turnover-growth score |
| valuation_score | double | `100 - valuation_percentile` |
| structure_score | double | Manual ETF structure quality score |
| liquidity_score | double | Cross-sectional 20-day turnover score |
| risk_score | double | Volatility/drawdown/overheat risk score, higher is safer |
| state | string | Interpretable state label such as `景气上行 + 动量确认` |
| action | string | Research action label such as `主线候选`, `左侧观察`, or `暂不优先` |

## Portfolio Advice

API endpoint: `POST /api/portfolio/advice`

Job option: `python -m app.jobs.daily_signal --holdings-file <csv-or-json>`

Portfolio advice compares current holdings with a risk-adjusted target portfolio
built from current rotation candidates. It is a research adjustment view, not an
order ticket.

Request fields:

| Field | Type | Description |
| --- | --- | --- |
| holdings | array | Current holdings with `symbol` and `weight` |
| target_count | integer | Number of target rotation candidates to include, default `5` |
| universe_limit | integer | Number of ranked ETFs to inspect from the rotation radar, default `50` |
| min_trade_weight | double | Minimum weight difference for an adjustment label, default `0.03` |

Holding fields:

| Field | Type | Description |
| --- | --- | --- |
| symbol | string | Standard ETF symbol, e.g. `159998.SZ` |
| weight | double | Current portfolio weight from 0 to 1; `0.30` means 30% |

Response fields:

| Field | Type | Description |
| --- | --- | --- |
| radar_date | date | Rotation radar date used for the advice |
| current_exposure | double | Sum of current input weights |
| target_exposure | double | Realized target ETF exposure after risk caps |
| cash_weight | double | Residual cash or low-risk weight implied by target exposure |
| estimated_turnover | double | Half of absolute current-vs-target weight changes |
| market_regime | object | Market regime snapshot used for target exposure |
| target_symbols | array | Symbols selected for the target portfolio |
| advice | array | Per-symbol adjustment rows |
| data_notes | array | Research caveats and risk-constraint notes |

Advice row fields:

| Field | Type | Description |
| --- | --- | --- |
| symbol | string | ETF symbol |
| name | string | ETF display name |
| theme | string | Inferred theme |
| etf_type | string | ETF type used by the radar |
| current_weight | double | Current input portfolio weight |
| target_weight | double | Risk-adjusted target portfolio weight |
| delta_weight | double | `target_weight - current_weight` |
| action | string | `新增配置候选`, `加仓候选`, `减仓候选`, or `持有不变` |
| total_score | double | Rotation total score when available |
| state | string | Rotation state label when available |
| rotation_action | string | Original rotation action label when available |
| rationale | array | Human-readable reasons for the action label |
| drivers | array | Positive rotation drivers |
| risk_notes | array | Rotation or missing-data risk notes |

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
