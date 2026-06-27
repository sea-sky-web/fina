# One-Week Quantitative Development Plan

**Date**: 2026-06-19 to 2026-06-26  
**Context**: Fina ETF Research Dashboard — P0 complete, P1 partially done, P3/P4 largely complete  
**Focus**: P1 data quality closure + P2 Qlib export + testing & resilience hardening

---

## Current State Assessment

| Priority | Status | Completion |
|----------|--------|------------|
| P0: Data Foundation | ✅ Complete | 8/8 tasks |
| P1: Data Quality | 🔶 Partial | 3/7 tasks done |
| P2: Qlib Export | ❌ Not started | 0/5 tasks |
| P3: Factor Research | ✅ Near complete | 7 factors, full eval pipeline |
| P4: Backtesting | ✅ Near complete | Walk-forward, risk, dynamic weights |

**Open gaps (P1)**: data validation, configurable retry, normalizer tests, DuckDB views, full-refresh CLI  
**Open gaps (P2)**: Qlib export script, calendars, instruments, features, adjustment policy docs  
**Tech debt**: FactorPanel hardcoded to momentum_60d in frontend

---

## Day 1 (Fri 6/19): Data Validation Layer

**Goal**: Add systematic data quality checks so the dashboard never silently shows corrupt data.

### Tasks

| # | Task | Files | Est. | Metric |
|---|------|-------|------|--------|
| 1.1 | Create `app/validation/` module with `DataValidator` class | `app/validation/__init__.py`, `app/validation/checks.py` | 2h | Module compiles, passes lint |
| 1.2 | Implement `validate_etf_daily()` — checks for: missing dates per symbol, duplicate (symbol, date) rows, open>high or low>close, volume ≤ 0, amount ≤ 0, close ≤ 0, pct_chg > 15% intraday | `app/validation/checks.py` | 2h | All 7 check types return structured results |
| 1.3 | Implement `validate_etf_basic()` — checks for: duplicate symbols, missing required fields, invalid exchange suffix, negative prices | `app/validation/checks.py` | 1h | 4 check types returning structured results |
| 1.4 | Add `ValidationReport` Pydantic model | `app/models/validation.py` | 30m | Model with per-check severity (ok/warning/error), counts, and sample rows |
| 1.5 | Write tests for validator | `tests/test_validation.py` | 1.5h | ≥ 10 test cases, ≥ 80% line coverage on validation module |
| 1.6 | Wire into `/api/status` response — add `validation` field to data status | `app/services/status_service.py`, `app/api/v1/status.py` | 30m | API returns validation field, frontend status cards show warnings |

**Day 1 target**: `ruff check` clean, `pytest tests/test_validation.py` green, API returns per-dataset validation status.

---

## Day 2 (Sat 6/20): Provider Resilience

**Goal**: Make data collection survive unstable AKShare endpoints with configurable retry.

### Tasks

| # | Task | Files | Est. | Metric |
|---|------|-------|------|--------|
| 2.1 | Add retry config to Settings: `FINA_COLLECTOR_RETRY_COUNT=3`, `FINA_COLLECTOR_RETRY_BACKOFF=1.0`, `FINA_COLLECTOR_RETRY_TIMEOUT=30` | `app/core/config.py` | 30m | Settings load from env, sensible defaults |
| 2.2 | Implement `retry_collect()` decorator in `app/collectors/retry.py` — exponential backoff, per-endpoint timeout, preserves last exception with context | `app/collectors/retry.py` | 1.5h | Decorator wraps any collector method, ≤ 20 lines of caller code |
| 2.3 | Apply retry to `AkshareEtfCollector.fetch_etf_universe()` and `fetch_daily_bars()` | `app/collectors/akshare_collector.py` | 30m | Both methods retry on network/timeout errors, skip retry on data-format errors |
| 2.4 | Add `RetryRecord` to collection manifest — count attempts per endpoint, last error message | `app/jobs/collect_top_etfs.py` | 1h | Manifest includes retry stats per API call |
| 2.5 | Write tests for retry decorator — success on retry-2, exhaust retries, non-retryable error | `tests/test_collector_retry.py` | 1.5h | 5+ test cases with mock AKShare |
| 2.6 | Add frontend indicator: "数据源状态" card in StatusPanel showing last provider error if any | `frontend/src/components/StatusPanel.tsx`, `frontend/src/types/etf.ts` | 1h | Red/yellow/green dot + last error message tooltip |

**Day 2 target**: Collection survives 3 consecutive AKShare timeouts, manifest records every retry attempt, frontend shows provider health.

---

## Day 3 (Sun 6/21): Qlib Export — Core Script

**Goal**: Rebuildable Qlib dataset from clean Parquet, with documented limitations.

### Tasks

| # | Task | Files | Est. | Metric |
|---|------|-------|------|--------|
| 3.1 | Create `app/jobs/export_qlib.py` CLI script — `--calendar`, `--instruments`, `--features`, `--all` flags | `app/jobs/export_qlib.py` | 1h | `python -m app.jobs.export_qlib --help` works |
| 3.2 | Generate Qlib calendar — list of trading days from `etf_daily.parquet` date column, format as Qlib `calendars/day.txt` | `app/jobs/export_qlib.py` | 1h | Calendar file written, one date per line YYYYMMDD |
| 3.3 | Generate Qlib instruments — ETF list from `etf_basic.parquet`, format as Qlib `instruments/all.txt` with start/end dates per symbol | `app/jobs/export_qlib.py` | 1h | Instruments file with symbol, start_date, end_date columns |
| 3.4 | Generate Qlib features — pivot `etf_daily.parquet` to Qlib binary format: `open,high,low,close,volume,amount,factor` per symbol per day. Save to `data/qlib/features/<symbol>/` | `app/jobs/export_qlib.py` | 2h | Features directory populated, Qlib `qlib.init()` can load them |
| 3.5 | Add `factor` column policy: write `1.0` for all rows since AKShare doesn't provide adjustment factors. Document the limitation in the script docstring | `app/jobs/export_qlib.py` | 30m | Decision documented, factor column present and consistently 1.0 |
| 3.6 | Verify round-trip: export → `qlib.data.dataset.DatasetH` can load → `dataset.prepare()` succeeds | Manual test | 30m | Qlib loads without error, basic data inspection works |

**Day 3 target**: `python -m app.jobs.export_qlib --all` generates complete Qlib dataset that passes `qlib.init()` and `DatasetH` loading.

---

## Day 4 (Mon 6/22): Normalizer Tests + DuckDB Views

**Goal**: Close testing gaps and add convenient query layer.

### Tasks

| # | Task | Files | Est. | Metric |
|---|------|-------|------|--------|
| 4.1 | Write tests for `AKShareNormalizer.normalize_spot()` — normal columns, missing columns, empty frame, 52-prefix edge case, bad symbol format | `tests/test_normalizers.py` | 1.5h | 6+ test cases covering success + edge cases |
| 4.2 | Write tests for `AKShareNormalizer.normalize_daily()` — sina vs em endpoint outputs, date parsing, price coercion, NaN handling | `tests/test_normalizers.py` | 1.5h | 6+ test cases |
| 4.3 | Add DuckDB convenience views: `CREATE VIEW etf_latest AS ...`, `CREATE VIEW etf_daily_latest_60d AS ...`, `CREATE VIEW factor_latest_scores AS ...` | `app/storage/duckdb_views.py` | 1.5h | 3+ views, each queryable via `duckdb.sql("SELECT * FROM <view>")` |
| 4.4 | Add `GET /api/etfs/latest` endpoint — returns ETF list with latest price/volume/amount/chg using DuckDB view | `app/api/v1/etfs.py`, `app/services/etf_service.py` | 1.5h | Endpoint returns ≤ 50ms for 100 ETFs |
| 4.5 | Add test for DuckDB views — views return correct row counts, no stale symbols | `tests/test_duckdb_views.py` | 1h | 3+ test cases |

**Day 4 target**: Normalizer test coverage > 80%, 3 DuckDB views working, latest-ETF endpoint returns correct data.

---

## Day 5 (Tue 6/23): Full-Refresh CLI + Frontend Hardcoding Fix

**Goal**: One-command rebuild and dynamic factor panel.

### Tasks

| # | Task | Files | Est. | Metric |
|---|------|-------|------|--------|
| 5.1 | Build `app/jobs/full_refresh.py` — calls `collect_top_etfs` → `rebuild_factors` → `export_qlib` in sequence, with per-stage timing and error isolation (one stage fails doesn't block others) | `app/jobs/full_refresh.py` | 1.5h | `python -m app.jobs.full_refresh` runs all 3 stages, prints summary table |
| 5.2 | Update `POST /api/refresh/top-etfs` to accept optional `?rebuild_factors=true&export_qlib=true` query params, so the frontend refresh button can trigger the full pipeline | `app/api/v1/refresh.py`, `app/services/refresh_service.py` | 1h | API supports chain refresh |
| 5.3 | Fix FactorPanel hardcoding — read factor list from `GET /api/factors/definitions`, render dropdown with all 7 factors, default to `momentum_60d` | `frontend/src/components/FactorPanel.tsx` | 1.5h | FactorPanel shows factor selector, switching factors re-fetches and re-renders |
| 5.4 | Update `useFactorResearch` hook to accept `factorName` parameter dynamically | `frontend/src/hooks/useFactorResearch.ts` | 1h | Hook refetches on factorName change |
| 5.5 | Add factor name selector to FactorDiagnosticsPanel and FactorHistoryChart — consistent with FactorPanel | `frontend/src/components/FactorDiagnosticsPanel.tsx`, `frontend/src/components/FactorHistoryChart.tsx` | 1.5h | All factor components use dynamic factor selection |

**Day 5 target**: One-click full pipeline from frontend, all factor UI components dynamically selectable.

---

## Day 6 (Wed 6/24): Edge Case Hardening

**Goal**: Handle real-world data scenarios that break naive assumptions.

### Tasks

| # | Task | Files | Est. | Metric |
|---|------|-------|------|--------|
| 6.1 | Handle empty/single-symbol edge cases in factor computation — `rebuild_factors` crashes with `< 2 symbols` for rank | `app/services/factor_service.py` | 1h | Graceful skip with log warning when < min_cross_section_size |
| 6.2 | Handle division-by-zero in all factor formulas: `momentum` (close_60d_ago = 0), `volatility` (single day), `risk_adjusted_return` (volatility = 0), `liquidity_stability` (std = 0) | Individual factor files under `app/factors/` | 1.5h | All 7 factors return NaN (not crash) on degenerate inputs |
| 6.3 | Handle stale/empty data path in all services — graceful fallback with clear error messages | `app/services/*.py` | 1h | Every service function handles empty Parquet without traceback |
| 6.4 | Add data integrity test: run `collect_top_etfs --limit 100 --lookback-days 365` followed by `rebuild_factors --lookback-days 60`, verify no NaN in rank/percentile columns | `tests/test_integration.py` | 1.5h | End-to-end pipeline runs, output factors file has zero NaN ranks |
| 6.5 | Add CI-like check: `ruff check && pytest && npm run lint && npm run build` — verify everything passes from scratch | Manual + script | 30m | All 4 commands exit 0 |
| 6.6 | Fix any bugs found during integration test, re-run until green | Various | 1h | Integration test passes |

**Day 6 target**: Zero crashes on edge cases, integration test green, full lint+test+build chain passes.

---

## Day 7 (Thu 6/25): Documentation + Polish + Release Notes

**Goal**: Make the project self-documenting and ready for the next phase.

### Tasks

| # | Task | Files | Est. | Metric |
|---|------|-------|------|--------|
| 7.1 | Update `docs/DATA_CONTRACT.md` — add Qlib export format section, factor adjustment policy | `docs/DATA_CONTRACT.md` | 30m | Qlib section documents all fields and limitations |
| 7.2 | Update `docs/GOALS_AND_TASKS.md` — mark completed P1/P2 tasks, add notes on what was implemented | `docs/GOALS_AND_TASKS.md` | 30m | Current state accurately reflected |
| 7.3 | Write `docs/FACTOR_METHODOLOGY.md` — one-page per factor: formula, lookback rationale, known limitations, interpretation guidance | `docs/FACTOR_METHODOLOGY.md` | 1.5h | 7 factor sections, each with formula + interpretation |
| 7.4 | Add docstrings to all public functions in `app/services/`, `app/collectors/`, `app/normalizers/` that are missing them | Various | 1.5h | All public functions have docstrings with Args/Returns |
| 7.5 | Update CLAUDE.md — add Qlib export command, validation module, full-refresh CLI, any new API routes | `CLAUDE.md` | 30m | CLAUDE.md reflects week's changes |
| 7.6 | Write `CHANGELOG.md` — one-week summary: what was built, what was fixed, known limitations, next priorities | `CHANGELOG.md` | 30m | Clear summary of 20+ deliverables |
| 7.7 | Final verification — `ruff check`, `pytest`, `npm run build` all green, dev server starts, frontend renders all panels | Manual | 30m | All checks pass |

**Day 7 target**: Documentation complete, all checks green, project ready for P3 expansion or production deployment research.

---

## Week Summary Metrics

| Dimension | Start | Target | Measure |
|-----------|-------|--------|---------|
| Data validation rules | 0 | 11 | Count of automated checks |
| Provider retry coverage | 0 methods | 2 methods | Decorated collector methods |
| Normalizer test coverage | ~0% | ≥ 80% | Line coverage on `app/normalizers/` |
| Qlib dataset rebuild | Missing | Working | `export_qlib --all` generates loadable dataset |
| DuckDB views | 0 | 4 | Named views queryable |
| One-click full refresh | Missing | Working | Frontend button → data + factors + qlib |
| Factor panel dynamic | Hardcoded | User-selectable | Dropdown with 7 factors |
| Edge case crashes | Unknown | 0 known | Integration test covers empty/single/NaN paths |
| Doc coverage | Partial | Complete | Factor methodology, Qlib spec, CHANGELOG |

## Key Risks

- **AKShare instability**: Days 2 and 6 may need extra time if the upstream API changes during the week. Mitigation: retry logic (Day 2) is built first, so subsequent work is protected.
- **Qlib compatibility**: Qlib expects specific binary formats; Day 3 may need adjustment if our Parquet pivot doesn't match Qlib's expected schema. Mitigation: verify round-trip same day.
- **Frontend factor refactor**: The hardcoded factor assumption may be deeper than just FactorPanel. Mitigation: Day 5 task 5.3 includes a sweep for all hardcoded factor references.

## Next Week Preview

After this week:
- P2 fully complete → start P3 expansion: more factors (e.g., Amihud illiquidity, volume-weighted momentum, sector-relative strength)
- Factor combination research — ICIR-based dynamic weighting → grid of factor combinations → selection stability analysis
- Performance attribution — decompose backtest returns into factor contributions
- Data pipeline scheduling — cron-based auto-refresh with health monitoring
