# Frontend and Backend Interaction Flow

## Purpose

This note records how the current React dashboard talks to the FastAPI backend. It is meant as a maintenance map for future feature work; the API contracts and research logic remain defined by the service modules and Pydantic models.

## High-Level Flow

```text
Refresh button
  -> POST /api/refresh/top-etfs
  -> collectors write raw parquet and clean parquet
  -> dashboard reloads status, ETF list, factor definitions, and research signals

Factor rebuild job
  -> app.services.factor_service.rebuild_factors()
  -> writes data/clean/factors.parquet and data/clean/factors_processed.parquet
  -> factor views, evaluation, signals, and backtests read the processed file

Factor research tab
  -> GET /api/factors
  -> GET /api/factors/diagnostics
  -> GET /api/evaluation/{factor}/report
  -> GET /api/evaluation/pool-report

Strategy tab
  -> GET /api/backtests/research-signal
  -> GET /api/backtests/walk-forward

Data tab
  -> GET /api/status
  -> GET /api/signals/performance
  -> POST /api/signals/snapshot
```

## Frontend Modules

- `src/api/client.ts`: typed HTTP wrapper and endpoint parameters.
- `src/constants/research.ts`: shared UI constants such as workspace keys, default factor, and strategy defaults.
- `src/hooks/useDashboardData.ts`: status, ETF universe, factor definitions, research signal list, and selected symbol.
- `src/hooks/useSelectedEtfData.ts`: selected ETF daily bars, selected signal detail, and factor history overlay.
- `src/hooks/useFactorResearch.ts`: factor scores plus lazy factor diagnostics and evaluation reports.
- `src/hooks/useStrategyValidation.ts`: strategy parameters and explicit backtest / walk-forward execution.
- `src/hooks/useSignalPerformance.ts`: lazy signal performance readback and refresh after snapshots.
- `src/pages/App.tsx`: UI composition, workspace switching, filtering, and top-level action handlers.

## Backend Modules

- `app/api/v1/*`: HTTP routes only; these should delegate to services.
- `app/services/etf_service.py`: read clean ETF basic and daily data.
- `app/services/factor_service.py`: factor rebuild and factor views.
- `app/services/evaluation_service.py`: IC, quantile returns, correlation, turnover, and pool reports.
- `app/services/signal_service.py`: current research score synthesis.
- `app/services/backtest_service.py`: research signal backtest and walk-forward orchestration.
- `app/services/cache.py`: clean parquet fingerprinting and bounded in-memory caches.
- `app/factors/processing/*`: raw factor processing pipeline.
- `app/synthesis/*`: factor weighting and selection rules.
- `app/backtest/*`: reusable walk-forward and attribution helpers.
- `app/monitoring/signal_tracker.py`: signal snapshot and performance review.

## Computation Rules

- GET endpoints should read cached artifacts or compute read-only reports; they must not rebuild clean data or factor parquet files.
- Heavy validation endpoints should be invoked explicitly from the UI, not on every parameter change.
- Cached reports are keyed by request parameters and clean parquet file fingerprints, so updating clean data invalidates stale cached results automatically.
- The frontend should prefer processed factors for research views to keep factor tables, evaluation, signals, and backtests aligned.
