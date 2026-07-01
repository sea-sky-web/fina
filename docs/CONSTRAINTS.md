# Project Constraints

## Scope

This project is limited to exchange-traded funds listed on Shanghai Stock Exchange and Shenzhen Stock Exchange.

Do not add:

- Individual stock recommendation
- Futures, options, crypto, or US ETF scope
- Broker order placement
- Real-money automated trading
- Investment advice phrased as buy/sell instructions

## Data Source Rules

Initial provider:

- AKShare for quick local development and public ETF market data.

Planned provider:

- Tushare Pro for more standardized ETF metadata, daily bars, NAV, and adjustment factors when credentials and permissions are available.

Official exchange pages may be used for validation, but they should not be the only source for historical research data unless an explicit structured download path is implemented.

## Data Quality Rules

Every collected dataset should record:

- Provider name
- Collection timestamp
- Source endpoint or function name
- Trade date or data date when available
- Row count
- Error details for failures

Clean data must normalize:

- ETF code into `symbol`, for example `510300.SH` and `159919.SZ`
- Date into ISO `YYYY-MM-DD`
- Numeric columns into stable numeric types
- Volume and amount units into documented units

## Rotation Data Compatibility

Clean daily market data should preserve at least:

```text
symbol, date, open, high, low, close, volume, amount, factor
```

The rotation service currently requires `symbol`, `date`, `close`, and preferably
`amount`. If `amount` is unavailable, liquidity scores should fall back to neutral
or clearly note the limitation.

Do not feed raw provider columns directly into the scoring service.

## API and Report Rules

The backend API and daily report are research outputs, not recommendation products.

They should show:

- Data freshness
- ETF ranking and score breakdown
- State pools and research actions
- Position-aware research adjustment labels when the user provides current holdings
- Collection failures or stale data warnings
- Manual input caveats

They should not show:

- Buy/sell labels
- Broker order instructions
- Target prices
- Guaranteed return language
- Ranking framed as investment advice

Portfolio advice may use labels such as `新增配置候选`, `加仓候选`, `减仓候选`,
and `持有不变` only when they are derived from current weight versus target
research weight. These labels must be accompanied by rationale and data caveats,
and must not be framed as an instruction to place an order.

## Automation Rules

Scheduled jobs should produce a full markdown report and JSON artifact. Notification
failures should be visible in GitHub Actions logs. The default notification channel
is a GitHub Issue so no third-party webhook secret is required.

## Local Data Rules

Real data files under `data/raw` and `data/clean` are local artifacts and should not be committed by default.
