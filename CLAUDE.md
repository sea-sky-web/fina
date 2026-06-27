# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fina is a China-listed ETF research dashboard. It collects ETF spot/daily data from AKShare, stores it as normalized Parquet files, and serves it via FastAPI to a React frontend. The goal is a research tool — not a trading system, not investment advice.

## Commands

### Backend (Python 3.11+, from repo root)

```bash
# Install
python3.11 -m venv backend/.venv && source backend/.venv/bin/activate && pip install "./backend[dev]"

# Dev server
PYTHONPATH=backend uvicorn app.main:app --reload

# Tests
cd backend && python -m pytest

# Lint
cd backend && ruff check .

# Collect top-100 ETF data (spot + 1yr daily bars)
PYTHONPATH=backend python -m app.jobs.collect_top_etfs --limit 100 --lookback-days 365

# Rebuild factors from clean daily data
PYTHONPATH=backend python -m app.jobs.rebuild_factors --lookback-days 60
```

### Frontend (from repo root)

```bash
cd frontend && npm install
npm run dev       # starts on :5173, proxies /api to :8000
npm run build     # tsc -b && vite build
npm run lint      # eslint
```

## Architecture

### Data flow

```
AKShare → collectors → raw/ parquet → normalizers → clean/ parquet → services → API routes → React
                                                                          ↑
                                                                   DuckDB (query layer, not source of truth)
```

Refreshes use **atomic replace**: write new data to a temp dir, then `os.replace()` over the clean files. If a provider request fails, the system falls back to cached data (raw first, then clean) and marks the run as `degraded`.

### Backend layer responsibilities

| Layer | Dir | Role |
|-------|-----|------|
| Config | `app/core/` | Settings from env vars (`FINA_` prefix), project root detection |
| Collectors | `app/collectors/` | Provider-specific fetching. Must NOT be called from API routes directly. |
| Normalizers | `app/normalizers/` | Transform raw provider DataFrames into the clean data contract (see `docs/DATA_CONTRACT.md`) |
| Storage | `app/storage/` | Parquet read/write + DuckDB convenience queries |
| Services | `app/services/` | Domain logic used by API routes |
| API | `app/api/` | Thin route definitions, delegates to services |
| Jobs | `app/jobs/` | CLI-entry scripts for data collection and factor rebuild |
| Models | `app/models/` | Pydantic models shared between services and API |

### API route structure

- `GET /health` — health check
- `GET /api/status` — data freshness for each dataset
- `GET /api/etfs?limit=` — ETF universe sorted by turnover
- `GET /api/etfs/{symbol}/daily` — OHLCV bars for one ETF
- `GET /api/factors?name=&limit=` — factor scores
- `POST /api/factors/rebuild?lookback_days=` — rebuild factors
- `POST /api/refresh/top-etfs?limit=&lookback_days=` — trigger full data collection

### Frontend component tree

```
App
├── StatusPanel (data freshness cards + refresh button)
├── EtfTable (filterable ETF list with theme tabs)
├── PriceChart (SVG candlestick + volume chart for selected ETF)
└── FactorPanel (factor score rankings table)
```

Theme filtering applies to both the ETF table and FactorPanel in sync. Selecting an ETF updates the price chart.

### Key design decisions

- **ETF universe selection**: top-N by turnover amount (`成交额`), not by market cap or fund size.
- **Symbol format**: `510300.SH`, `159915.SZ` — six-digit code + exchange suffix.
- **Provider isolation**: AKShare imports only exist inside `collectors/` and `normalizers/`. Swapping AKShare for Tushare means writing a new collector + normalizer pair.
- **Factor storage**: all factors live in a single `factors.parquet` with a `factor_name` column. Each row is one symbol-date-factor combination with value, rank, and percentile.
- **Theme classification**: rule-based keyword matching in `theme_classifier.py`, applied at read time (not stored).
- **Sample/fallback data**: `etf_service.py` returns hardcoded sample data when Parquet files are empty, so the frontend always renders something.
- **Pre-commit safety**: data files under `data/` are gitignored. Never commit real market data.

### Factor system (current state)

Currently only `momentum_60d` is implemented, hardcoded in `factor_service.py`. The factor is: `close_today / close_60_days_ago - 1`, computed per symbol, then cross-sectionally ranked and percentiled per date. The `FactorPanel` frontend is also hardcoded to this single factor. See `docs/GOALS_AND_TASKS.md` P3 for the full factor roadmap (volatility, turnover, liquidity stability, drawdown, risk-adjusted return).
