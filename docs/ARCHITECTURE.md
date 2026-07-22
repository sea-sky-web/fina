# Architecture

## Goal

Fina is now a backend-first China-listed ETF rotation radar. The system is not a
price prediction tool and does not place trades. It produces a repeatable daily
research report that ranks industry and theme ETFs by cycle, momentum, valuation,
structure, liquidity, and risk.

The v0.1 system answers:

- Which industry or theme ETFs currently deserve attention?
- Which ETFs combine stronger cycle score and confirmed momentum?
- Which ETFs look like low-priority, crowded, or value-trap candidates?
- Is the underlying ETF market data fresh enough to trust the report?

## Data Flow

```text
AKShare
  -> collectors
  -> raw parquet
  -> clean ETF basic and daily parquet
  -> manual rotation inputs from config/etf_rotation_inputs.csv
  -> rotation scoring service
  -> FastAPI /api/rotation/report
  -> optional current holdings
  -> portfolio advice service
  -> FastAPI /api/portfolio/advice
  -> daily_signal CLI markdown + JSON
  -> GitHub Actions issue notification
```

Refreshes must preserve the previous clean dataset when the latest provider request
fails. If the spot universe request fails but a cached clean ETF universe exists,
the refresh may reuse that cached universe and still refresh daily bars. If a
daily-bar request fails for a symbol but cached daily bars exist, the refresh may
reuse the cached bars and mark the run as degraded.

## Backend Layers

- `app/core`: configuration and shared infrastructure
- `app/collectors`: provider-specific data collection
- `app/storage`: parquet persistence
- `app/services`: domain logic used by API routes and jobs
- `app/api`: HTTP routes and response schemas
- `app/jobs`: scheduled or manual CLI entry points

Provider-specific code must stay inside `collectors`. API routes should not call
AKShare or Tushare directly.

## Rotation Service

`app/services/rotation_service.py` is the single source for the v0.1 ranking logic.
Both `GET /api/rotation/report` and `python -m app.jobs.daily_signal` call this
service so the API and scheduled report stay aligned.

Inputs:

- clean ETF daily bars: price and amount
- clean ETF basic metadata: symbol, name, index name
- manual rotation input CSV: theme, ETF type, boom score, valuation percentile,
  structure score, and notes

Processing:

- infer ETF theme and type
- calculate 1m/3m/6m returns
- calculate relative strength versus `510300.SH`
- calculate moving-average status, 20-day amount, amount growth, volatility, and
  drawdown
- combine cycle, momentum, valuation, structure, liquidity, and risk scores
- assign state labels and research actions

Outputs:

- ranked ETF table
- per-ETF drivers and risk notes
- state pools: `core_candidates`, `watchlist`, and `avoid`
- data caveats for stale or incomplete inputs

## Portfolio Advice Service

`app/services/portfolio_advice_service.py` turns the rotation radar into a
position-aware research output. It does not replace the rotation service. Instead,
it compares current portfolio weights with a risk-adjusted target portfolio built
from current core rotation candidates.

Inputs:

- current holdings: `symbol` and portfolio `weight`
- latest rotation report
- clean ETF daily bars for market regime and correlation constraints

Processing:

- choose target symbols from `主线候选` and `重点跟踪`
- detect market regime and target exposure
- apply risk constraints for single ETF, theme concentration, and correlation clusters
- compare current weights with target weights
- assign research adjustment labels: `新增配置候选`, `加仓候选`, `减仓候选`, or `持有不变`

Outputs:

- current exposure, target exposure, cash/low-risk weight, and estimated turnover
- per-symbol current weight, target weight, delta, action label, and rationale
- data notes that keep the output framed as research, not trading instructions

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

### Manual Inputs

Research judgement that v0.1 cannot infer automatically.

Example:

```text
config/etf_rotation_inputs.csv
```

### Query

DuckDB views/tables are a convenience query layer, not the source of truth.

## Rotation Backtest Strategy (`scripts/rotation/`)

Standalone walk-forward backtest for the ETF rotation strategy, independent of the
backend application. Does not import from `app.*`.

```text
data/clean/etf_daily.parquet
  -> scripts/build_backtest_data.py (filter, validate)
  -> data/research/etf_daily_backtest.parquet
  -> scripts/rotation/ package (walk-forward backtest)
  -> artifacts/backtest_v64/ (report.json, windows.csv)
```

The package is modularized into 9 files:

- `config.py`: `StrategyConfig` dataclass — all strategy parameters in one place
- `data.py`: data loading, liquidity filter, common history alignment
- `signals.py`: dual-period momentum z-score, relative strength, volume-price bonus
- `engine.py`: daily simulation loop (stop-loss, drawdown breaker, re-entry, scaling)
- `metrics.py`: pure performance metric functions (reusable by any strategy)
- `walkforward.py`: expanding-window walk-forward with grid search over K
- `report.py`: cost erosion analysis and 8-item judge checklist
- `__main__.py`: entry point

Strategy variations are achieved by passing different `StrategyConfig` instances,
not by creating new script files. Version history is tracked via git.
