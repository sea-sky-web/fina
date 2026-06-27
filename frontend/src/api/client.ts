import type {
  BacktestResult,
  DataStatus,
  EtfBasic,
  EtfDailyBar,
  FactorDiagnostics,
  FactorDefinition,
  FactorEvaluationReport,
  FactorHistoryPoint,
  FactorPoolEvaluationReport,
  FactorScore,
  MonitoringReport,
  RefreshResult,
  ResearchSignal,
  SignalPerformance,
  SignalSnapshotResult,
  WalkForwardResult,
} from "../types/etf";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method: "POST" });
  const payload = (await response.json()) as T;
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }
  return payload;
}

export function fetchDataStatus(): Promise<DataStatus[]> {
  return getJson<DataStatus[]>("/api/status");
}

export function fetchEtfs(limit = 100): Promise<EtfBasic[]> {
  return getJson<EtfBasic[]>(`/api/etfs?limit=${limit}`);
}

export function fetchEtfDaily(symbol: string): Promise<EtfDailyBar[]> {
  return getJson<EtfDailyBar[]>(`/api/etfs/${encodeURIComponent(symbol)}/daily`);
}

export function fetchFactorDefinitions(): Promise<FactorDefinition[]> {
  return getJson<FactorDefinition[]>("/api/factors/definitions");
}

export function fetchFactorHistory(
  symbol: string,
  name: string,
  processed = true
): Promise<FactorHistoryPoint[]> {
  return getJson<FactorHistoryPoint[]>(
    `/api/factors/history?symbol=${encodeURIComponent(symbol)}&name=${encodeURIComponent(name)}&processed=${processed}`
  );
}

export function fetchFactorScores(
  name: string,
  limit = 100,
  processed = true
): Promise<FactorScore[]> {
  return getJson<FactorScore[]>(
    `/api/factors?name=${encodeURIComponent(name)}&limit=${limit}&processed=${processed}`
  );
}

export function fetchFactorDiagnostics(
  name: string,
  horizon = 20,
  processed = true
): Promise<FactorDiagnostics> {
  const params = new URLSearchParams({
    name,
    horizon: String(horizon),
    processed: String(processed),
  });
  return getJson<FactorDiagnostics>(`/api/factors/diagnostics?${params.toString()}`);
}

export function fetchFactorEvaluationReport(name: string): Promise<FactorEvaluationReport> {
  return getJson<FactorEvaluationReport>(
    `/api/evaluation/${encodeURIComponent(name)}/report?horizons=1,5,10,20`
  );
}

export function fetchFactorPoolEvaluationReport(): Promise<FactorPoolEvaluationReport> {
  return getJson<FactorPoolEvaluationReport>("/api/evaluation/pool-report?horizons=1,5,10,20");
}

export function fetchResearchSignals(limit = 100, theme?: string): Promise<ResearchSignal[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (theme && theme !== "全部") {
    params.set("theme", theme);
  }
  return getJson<ResearchSignal[]>(`/api/signals?${params.toString()}`);
}

export function fetchResearchSignal(symbol: string): Promise<ResearchSignal> {
  return getJson<ResearchSignal>(`/api/signals/${encodeURIComponent(symbol)}`);
}

export function fetchResearchSignalBacktest(params: {
  start?: string;
  end?: string;
  topN?: number;
  costBps?: number;
  benchmark?: string;
} = {}): Promise<BacktestResult> {
  const query = new URLSearchParams({
    top_n: String(params.topN ?? 10),
    rebalance: "monthly",
    cost_bps: String(params.costBps ?? 5),
    benchmark: params.benchmark ?? "510300.SH",
  });
  if (params.start) {
    query.set("start", params.start);
  }
  if (params.end) {
    query.set("end", params.end);
  }
  return getJson<BacktestResult>(`/api/backtests/research-signal?${query.toString()}`);
}

export function refreshTopEtfs(limit = 100, lookbackDays = 365): Promise<RefreshResult> {
  return postJson<RefreshResult>(
    `/api/refresh/top-etfs?limit=${limit}&lookback_days=${lookbackDays}`
  );
}

export function fetchWalkForward(params: {
  trainMonths?: number;
  testMonths?: number;
  stepMonths?: number;
  topN?: number;
  costBps?: number;
} = {}): Promise<WalkForwardResult> {
  const query = new URLSearchParams({
    train_months: String(params.trainMonths ?? 24),
    test_months: String(params.testMonths ?? 6),
    step_months: String(params.stepMonths ?? 6),
    top_n: String(params.topN ?? 10),
    cost_bps: String(params.costBps ?? 5),
  });
  return getJson<WalkForwardResult>(`/api/backtests/walk-forward?${query.toString()}`);
}

export function takeSignalSnapshot(topN = 20): Promise<SignalSnapshotResult> {
  return postJson<SignalSnapshotResult>(`/api/signals/snapshot?top_n=${topN}`);
}

export function fetchSignalPerformance(
  lookbackDays = 90,
  horizonDays = 20,
): Promise<SignalPerformance[]> {
  return getJson<SignalPerformance[]>(
    `/api/signals/performance?lookback_days=${lookbackDays}&horizon_days=${horizonDays}`,
  );
}

export function fetchMonitoringReport(): Promise<MonitoringReport> {
  return getJson<MonitoringReport>("/api/monitoring/report");
}
