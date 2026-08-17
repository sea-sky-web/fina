# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fina is a China-listed ETF research dashboard. It collects ETF spot/daily data from AKShare, stores it as normalized Parquet files, and serves rotation radar results via FastAPI. The daily research report is delivered as a GitHub Issue via GitHub Actions. The goal is a research tool — not a trading system, not investment advice.

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

### Frontend

`frontend/index.html` is a single-file strategy dashboard (vanilla JS, no framework).

### Rotation Backtest Engine (`backend/app/rotation_engine/`)

The ETF rotation backtest engine lives inside the backend package so the live signal
service (`app/services/strategy_signal_service.py`) and the offline walk-forward
backtest share the same scoring/selection code:

```bash
# Run full walk-forward backtest
PYTHONPATH=backend backend/.venv/bin/python -m app.rotation_engine

# Multi-asset two-layer mode / triple validation
PYTHONPATH=backend backend/.venv/bin/python -m app.rotation_engine --multi
PYTHONPATH=backend backend/.venv/bin/python -m app.rotation_engine --validate

# Or via legacy wrapper
python scripts/rotation_backtest.py
```

Package structure:

| Module | Role |
|--------|------|
| `config.py` | `StrategyConfig` dataclass with all parameters, path constants |
| `data.py` | Load parquet, liquidity filter, common history alignment |
| `signals.py` | Dual-period momentum z-score, relative strength, volume-price confirmation |
| `engine.py` | Simulation loop: stop-loss, drawdown circuit breaker, re-entry, bear/bull scaling |
| `metrics.py` | Annualized return, max drawdown, Sharpe, Calmar (pure functions) |
| `walkforward.py` | Expanding-window walk-forward with grid search |
| `report.py` | Cost erosion test, 8-item judge checklist report |
| `__main__.py` | Entry point |

Data pipeline: `scripts/build_backtest_data.py` → `data/research/etf_daily_backtest.parquet` → `app/rotation_engine` → `artifacts/backtest_v64/`

### Strategy versioning

The live signal strategy is versioned via `config/strategy.json` (version string +
params + universe csv path). API surface is `/api/strategy/*`; no strategy version is
hardcoded in module or route names. State persists to `data/clean/strategy_state.json`.

## Architecture

### Data flow

```
AKShare → collectors → raw/ parquet → normalizers → clean/ parquet → services → API routes → frontend (single HTML)
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
| Storage | `app/storage/` | Parquet read/write helpers |
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

### Frontend

`frontend/index.html` — single-file strategy dashboard: signal ranking table, portfolio action cards, equity curve comparison (current strategy vs baseline vs CSI300). Vanilla JS, data from `/api/strategy/signal`.

### Key design decisions

- **ETF universe selection**: top-N by turnover amount (`成交额`), not by market cap or fund size.
- **Symbol format**: `510300.SH`, `159915.SZ` — six-digit code + exchange suffix.
- **Provider isolation**: AKShare imports only exist inside `collectors/` and `normalizers/`. Swapping AKShare for Tushare means writing a new collector + normalizer pair.
- **Factor storage**: all factors live in a single `factors.parquet` with a `factor_name` column. Each row is one symbol-date-factor combination with value, rank, and percentile.
- **Theme classification**: rule-based keyword matching in `theme_classifier.py`, applied at read time (not stored).
- **Sample/fallback data**: `etf_service.py` returns hardcoded sample data when Parquet files are empty, so the frontend always renders something.
- **Pre-commit safety**: data files under `data/` are gitignored. Never commit real market data.

### Factor system

13 factors implemented in `app/factors/`, registered in `app/factors/registry.py`: momentum, volatility, drawdown, RSI, turnover, turnover concentration, liquidity stability, trend strength, risk-adjusted return, reversal, momentum exhaustion, deviation rate, EPS revision. Processing pipeline: MAD outlier removal → z-score standardization → theme neutralization (`app/factors/processing/`).
