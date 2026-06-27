# Goals and Task Priorities

## Final Goal

Build a China-listed ETF research dashboard that helps study ETF data quality, liquidity, historical behavior, and eventually factor performance.

The project should remain a research and decision-support tool. It must not become an automated trading system or a product that gives direct buy/sell instructions.

## Product Constraints

### In Scope

- Shanghai and Shenzhen listed ETFs only
- ETF universe discovery
- ETF spot market data collection
- ETF daily OHLCV history collection
- Local data storage and freshness inspection
- Basic dashboard display
- Qlib-compatible clean data export
- ETF-oriented factor analysis after the data layer is stable
- Backtesting and comparison for research purposes

### Out of Scope

- Individual stock selection
- US ETFs, Hong Kong ETFs outside mainland-listed cross-border ETFs, futures, options, crypto, or funds that are not exchange-traded ETFs
- Broker integration
- Real-money order placement
- Automated trading
- Direct investment advice, target prices, or buy/sell labels
- Complex ML modeling before data quality and baseline factors are validated

## Priority Levels

### P0: Stable Data Foundation

Goal: make the collected ETF data trustworthy enough to display and reuse.

Tasks:

- Define and enforce standard ETF symbol format, such as `510300.SH` and `159915.SZ`
- Collect ETF spot data and select the top liquidity universe by turnover amount
- Collect historical daily OHLCV data for the selected ETF universe
- Save raw provider data and clean normalized data separately
- Show data freshness, row counts, and collection failures
- Add manual refresh from the frontend
- Make refresh failure visible instead of silently showing stale data
- Keep all investment language neutral and data-focused

Acceptance:

- Dashboard can show the latest selected ETF universe
- Dashboard can show historical price charts for each selected ETF
- User can tell when the data was last updated
- Data collection failures are visible
- Local clean data can be regenerated from collectors

### P1: Data Quality and Maintainability

Goal: make the data layer dependable enough for research.

Tasks:

- Add data validation for missing dates, duplicate rows, invalid prices, and abnormal volume or amount values
- Add retry and fallback rules for unstable providers
- Add a collection manifest for each run
- Add tests for normalizers and API services
- Add a simple CLI command for full refresh
- Add configuration for ETF universe size, lookback window, and provider choice
- Add DuckDB query views over clean Parquet files

Acceptance:

- A failed provider request does not corrupt existing clean data
- Tests cover the main normalization paths
- The API reads from a stable clean data contract
- The project can explain whether displayed data is fresh, stale, empty, or failed

### P2: Qlib Data Preparation

Goal: prepare the project for Qlib without mixing Qlib internals into the app data store.

Tasks:

- Export clean ETF daily data into Qlib-compatible input format
- Generate Qlib calendars, instruments, and features
- Preserve required fields: `symbol`, `date`, `open`, `high`, `low`, `close`, `volume`, `amount`, `factor`
- Decide adjusted or unadjusted price policy
- Document limitations when adjustment factors are unavailable
- Add a script to rebuild Qlib data from clean Parquet

Acceptance:

- Qlib dataset can be rebuilt from clean data
- Qlib output is treated as generated data
- Clean Parquet remains the source of truth
- Basic Qlib data loading succeeds for the ETF universe

### P3: ETF Factor Research

Goal: study whether simple ETF factors have useful historical behavior.

Tasks:

- Implement baseline ETF factors:
  - Momentum
  - Volatility
  - Turnover amount
  - Liquidity stability
  - Drawdown
  - Risk-adjusted return
- Avoid stock-only factors such as PE, PB, ROE, and accounting quality
- Add factor distribution and rank views
- Add historical factor return comparison
- Add benchmark comparison
- Add clear disclaimers that factor results are historical research only

Acceptance:

- Every factor has a documented definition
- Every factor can be reproduced from clean data
- Factor results can be inspected by date and ETF
- No factor output is framed as direct investment advice

### P4: Research Backtesting

Goal: compare simple ETF selection rules under realistic assumptions.

Tasks:

- Add simple rebalancing rules
- Add transaction cost assumptions
- Add benchmark comparison
- Add max drawdown, annualized return, volatility, Sharpe-like metrics, and win-rate style diagnostics
- Add train/test or time-split evaluation
- Make overfitting risk visible in the UI and docs

Acceptance:

- Backtests include costs
- Backtests avoid look-ahead bias
- Results are reproducible from stored clean data
- UI separates research results from current market data

## Current Next Tasks

P0 implementation status:

- Implemented: top liquidity ETF collection by turnover amount
- Implemented: historical daily OHLCV collection for the selected ETF universe
- Implemented: raw and clean data separation
- Implemented: dashboard status cards for row counts and collection state
- Implemented: frontend manual refresh
- Implemented: refresh failure warning
- Implemented: preserve previous clean data when refresh fails
- Implemented: degraded refresh with cached ETF universe and cached daily bars
- Implemented: tests for successful refresh and failed refresh preservation

Recommended next order:

1. Add broader data validation for missing dates, duplicate rows, invalid prices, and abnormal volume or amount values
2. Add provider retry policy with configurable retry count and timeout
3. Add DuckDB query layer
4. Add tests for AKShare normalizers
5. Add a full-refresh CLI wrapper
6. Add Qlib export script

## Decision Rules

- Prefer simple observable data before complex factors
- Prefer deterministic scripts before notebooks
- Prefer reproducible local data files before live-only views
- Prefer ETF-specific factors over stock-factor reuse
- Prefer visible stale-data warnings over silent refresh failures
- Do not add model training until P0, P1, and P2 are stable

## Success Definition

The project is successful when it can:

- Reliably collect and display mainland-listed ETF data
- Explain exactly when and how the data was collected
- Export clean data into Qlib-compatible format
- Run simple ETF factor research reproducibly
- Help the user learn factor investing without disguising historical analysis as investment advice
