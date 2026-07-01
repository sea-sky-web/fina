# Goals and Task Priorities

## Final Goal

Build a China-listed industry/theme ETF rotation radar that refreshes data daily,
scores ETFs with explicit assumptions, and sends a complete research report through
GitHub Issues.

The project should remain a research and decision-support tool. It must not become
an automated trading system or a product that gives direct buy/sell instructions.

## Product Constraints

### In Scope

- Shanghai and Shenzhen listed ETFs
- ETF universe discovery
- ETF daily OHLCV and amount collection
- Local data freshness inspection
- Manual industry/theme cycle and valuation inputs
- Rotation ranking and state classification
- Backend API, CLI report, and GitHub Actions automation

### Out of Scope

- Individual stock selection
- Broker integration
- Real-money order placement
- Automated trading
- Direct investment advice, target prices, or guaranteed return language
- Automatic NLP-based cycle scoring in v0.1
- Full ETF constituent-through analysis in v0.1

## Priority Levels

### P0: Stable Data Foundation

Goal: make the collected ETF data trustworthy enough to reuse in the radar.

Tasks:

- Define and enforce standard ETF symbol format, such as `510300.SH` and `159915.SZ`
- Collect ETF spot data and select the top liquidity universe by turnover amount
- Collect historical daily OHLCV data for the selected ETF universe
- Save raw provider data and clean normalized data separately
- Show data freshness, row counts, and collection failures
- Preserve previous clean data when provider refreshes fail

Acceptance:

- Clean ETF basic and daily parquet files can be regenerated
- A failed provider request does not corrupt existing clean data
- Report notes expose stale, empty, or degraded data

### P1: Rotation Radar v0.1

Goal: produce a repeatable, interpretable industry/theme ETF ranking.

Tasks:

- Maintain `config/etf_rotation_inputs.csv`
- Infer ETF theme and type from metadata
- Calculate 1m/3m/6m return and relative strength versus `510300.SH`
- Calculate moving-average, amount growth, volatility, and drawdown metrics
- Combine scores with transparent weights
- Assign state labels and research actions
- Expose the result through `GET /api/rotation/report`

Acceptance:

- API and CLI use the same scoring service
- Report includes ranking, score breakdown, per-ETF cards, state pools, and caveats
- Missing manual inputs default to neutral, not false certainty

### P2: Daily Automation and Notification

Goal: run the report automatically and make the full result visible without extra
notification secrets.

Tasks:

- Run GitHub Actions on trading weekdays
- Refresh ETF data before scoring
- Write markdown and JSON artifacts
- Create a GitHub Issue with the full markdown report
- Upload the report artifact for audit

Acceptance:

- Manual workflow dispatch works
- Scheduled workflow creates one issue containing the full report
- Failure to generate the report is visible in the workflow

### P3: Better Inputs

Goal: improve cycle, valuation, and structure inputs while keeping the cycle
signal data-driven and auditable.

Tasks:

- Add symbol-level overrides for important ETFs
- Add a review cadence for data-driven cycle proxy drift and manual overrides
- Add ETF size, fee, and tracking-index fields when reliable data is available
- Add valuation percentile ingestion when a stable source is selected
- Add optional constituent concentration once the data source is reliable

Acceptance:

- Manual input freshness is visible
- Each non-neutral manual cycle override has a short note
- Structure and valuation scores are auditable

## Decision Rules

- Prefer explainable state labels over opaque scores
- Prefer data freshness warnings over silent stale-data reuse
- Prefer manual judgement fields for hard-to-automate cycle inputs in v0.1
- Prefer backend APIs and scheduled reports over UI work
- Do not frame rankings as direct buy or sell instructions

## Success Definition

The project is successful when it can:

- Reliably collect mainland-listed ETF data
- Generate a daily rotation report automatically
- Explain each ETF's score with visible inputs and caveats
- Separate observation, configuration candidates, and avoid/control pools
- Keep the workflow reproducible through CLI, API, and GitHub Actions
