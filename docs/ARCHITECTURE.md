# Architecture

## Goal

Build a simple ETF data platform first, then add Qlib-based factor research later.

The first version only needs to answer:

- What ETFs are in the current universe?
- What recent market data do we have?
- When was the data last collected?
- Can the frontend inspect the collected data clearly?

## Data Flow

```text
AKShare / Tushare
  -> collectors
  -> raw parquet
  -> temporary normalized clean parquet
  -> atomic replace of clean parquet after full success
  -> DuckDB query layer
  -> FastAPI
  -> React dashboard
```

Refreshes must preserve the previous clean dataset when the latest provider request fails. If
the spot universe request fails but a cached clean ETF universe exists, the refresh may reuse
that cached universe and still refresh daily bars. If a daily-bar request fails for a symbol but
cached daily bars exist, the refresh may reuse the cached bars and mark the run as degraded.

Future Qlib flow:

```text
clean parquet
  -> qlib export dataset
  -> qlib dump_bin
  -> qlib features / alpha analysis
```

## Backend Layers

- `app/core`: configuration and shared infrastructure
- `app/collectors`: provider-specific data collection
- `app/storage`: parquet and DuckDB persistence
- `app/services`: domain logic used by API routes
- `app/api`: HTTP routes and response schemas

Provider-specific code must stay inside `collectors`. API routes should not call AKShare or Tushare directly.

## Frontend Layers

- `src/api`: typed API client
- `src/components`: reusable UI pieces
- `src/pages`: top-level screens
- `src/types`: shared TypeScript data contracts

The frontend should display data status clearly before any investment interpretation is added.

## Storage Layers

### Raw

Original provider output. Keep provider field names as much as possible.

Example:

```text
data/raw/akshare/etf_spot/date=20260521/part.parquet
```

### Clean

Normalized research-ready tables.

Example:

```text
data/clean/etf_basic.parquet
data/clean/etf_daily.parquet
```

### Query

DuckDB views/tables for API reads. DuckDB is a convenience query layer, not the source of truth.

### Qlib

Qlib-specific generated data. Treat it as rebuildable output.
