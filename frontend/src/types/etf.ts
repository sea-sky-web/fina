export type EtfBasic = {
  symbol: string;
  code: string;
  exchange: string;
  name: string;
  theme: string;
  full_name: string | null;
  index_code: string | null;
  index_name: string | null;
  manager: string | null;
  list_date: string | null;
  latest_price: number | null;
  pct_chg: number | null;
  volume: number | null;
  amount: number | null;
  status: string | null;
  provider: string;
  updated_at: string | null;
};

export type EtfDailyBar = {
  symbol: string;
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  pre_close: number | null;
  change: number | null;
  pct_chg: number | null;
  volume: number | null;
  amount: number | null;
  factor: number;
  provider: string;
  updated_at: string | null;
};

export type DataStatus = {
  provider: string;
  dataset: string;
  last_success_at: string | null;
  last_trade_date: string | null;
  rows: number;
  status: "ok" | "stale" | "empty" | "error";
  message: string;
};

export type RefreshResult = {
  ok: boolean;
  message: string;
  provider: string;
  selected_rows: number;
  daily_rows: number;
  factor_rows: number;
  factor_latest_date: string | null;
  refreshed_at: string | null;
  failures: Array<Record<string, string>>;
};

export type FactorDefinition = {
  name: string;
  label: string;
  description: string;
  lookback_days: string;
  direction: "higher_better" | "lower_better";
  category: "return" | "risk" | "liquidity" | "trend";
  format: "percent" | "amount" | "ratio";
  interpretation: string;
  limitation: string;
};

export type FactorHistoryPoint = {
  date: string;
  factor_value: number;
  rank: number;
  percentile: number;
};

export type FactorScore = {
  symbol: string;
  name: string;
  theme: string;
  date: string;
  factor_name: string;
  factor_value: number;
  rank: number;
  percentile: number;
  lookback_days: number;
  provider: string;
  updated_at: string | null;
};

export type SignalComponent = {
  factor_name: string;
  label: string;
  category: string;
  direction: "higher_better" | "lower_better";
  value_format: "percent" | "amount" | "ratio";
  factor_value: number;
  rank: number;
  percentile: number;
  weight: number;
  contribution: number;
  interpretation: string;
};

export type SignalExplanation = {
  positive_drivers: string[];
  risk_notes: string[];
  validation_notes: string[];
  data_notes: string[];
};

export type MarketRegimeSnapshot = {
  label: "risk_on" | "neutral" | "risk_off" | string;
  label_zh: string;
  date: string | null;
  target_exposure: number;
  trend_score: number | null;
  volatility_annualized: number | null;
  drawdown: number | null;
  source: string;
  data_notes: string[];
};

export type ResearchSignal = {
  symbol: string;
  name: string;
  theme: string;
  date: string;
  research_score: number;
  priority: string;
  components: SignalComponent[];
  explanation: SignalExplanation;
  market_regime: MarketRegimeSnapshot | null;
  target_exposure: number | null;
  provider: string;
  updated_at: string | null;
};

export type FactorDistribution = {
  count: number;
  missing_count: number;
  min: number | null;
  p25: number | null;
  median: number | null;
  p75: number | null;
  max: number | null;
  mean: number | null;
};

export type FactorForwardReturn = {
  horizon: number;
  sample_count: number;
  top_mean: number | null;
  bottom_mean: number | null;
  spread: number | null;
  data_notes: string[];
};

export type FactorStability = {
  lookback_dates: number;
  average_rank_change: number | null;
  label: string;
  data_notes: string[];
};

export type FactorDiagnostics = {
  factor_name: string;
  date: string | null;
  definition: FactorDefinition;
  distribution: FactorDistribution;
  top: FactorScore[];
  bottom: FactorScore[];
  forward_return: FactorForwardReturn;
  stability: FactorStability;
  data_notes: string[];
};

export type FactorICPoint = {
  date: string;
  ic_value: number;
};

export type FactorICStats = {
  factor_name: string;
  period_start: string | null;
  period_end: string | null;
  num_periods: number;
  rank_ic_mean: number | null;
  rank_ic_std: number | null;
  icir: number | null;
  ic_pos_ratio: number | null;
  ic_t_stat: number | null;
  ic_series: FactorICPoint[];
  ic_by_horizon: Record<string, number | null>;
};

export type FactorQuantilePoint = {
  date: string;
  returns: Record<string, number | null>;
};

export type FactorQuantileReturns = {
  factor_name: string;
  horizon_days: number;
  num_quantiles: number;
  quantile_returns: Record<string, number | null>;
  spread: number | null;
  is_monotonic: boolean;
  quantile_series: FactorQuantilePoint[];
};

export type RedundantFactorPair = {
  factor_a: string;
  factor_b: string;
  correlation: number;
};

export type FactorCorrelationMatrix = {
  date: string | null;
  factor_names: string[];
  matrix: Array<Array<number | null>>;
  redundant_pairs: RedundantFactorPair[];
};

export type FactorTurnoverStats = {
  factor_name: string;
  rank_autocorr: Record<string, number | null>;
  avg_turnover: number | null;
  migration_matrix: Array<Array<number | null>>;
};

export type FactorEvaluationReport = {
  factor_name: string;
  generated_at: string;
  period_start: string | null;
  period_end: string | null;
  num_assets_avg: number;
  ic: FactorICStats;
  quantile_returns: Record<string, FactorQuantileReturns>;
  correlations: FactorCorrelationMatrix | null;
  turnover: FactorTurnoverStats | null;
  warnings: string[];
  overall_verdict: "可用" | "待观察" | "不推荐单独使用";
};

export type FactorClusterGroup = {
  group: string;
  factors: string[];
};

export type FactorPoolEvaluationReport = {
  generated_at: string;
  individual_reports: FactorEvaluationReport[];
  correlation_matrix: FactorCorrelationMatrix;
  cluster_groups: FactorClusterGroup[];
  pool_health: "健康" | "冗余" | "因子不足";
  recommendations: string[];
};

export type BacktestConfig = {
  start: string | null;
  end: string | null;
  top_n: number;
  rebalance: string;
  cost_bps: number;
  benchmark: string;
};

export type BacktestMetrics = {
  cumulative_return: number | null;
  annualized_return: number | null;
  annualized_volatility: number | null;
  max_drawdown: number | null;
  sharpe_like: number | null;
  win_rate_daily: number | null;
  average_turnover: number | null;
  rebalance_count: number;
  final_equity: number | null;
};

export type BacktestEquityPoint = {
  date: string;
  equity: number;
  daily_return: number | null;
};

export type BacktestHolding = {
  symbol: string;
  name: string;
  theme: string;
  research_score: number;
  weight: number;
};

export type BacktestHoldingSnapshot = {
  rebalance_date: string;
  effective_date: string | null;
  holdings: BacktestHolding[];
  turnover: number;
  cost: number;
  regime: MarketRegimeSnapshot | null;
  target_exposure: number;
  realized_exposure: number;
  cash_weight: number;
  risk_notes: string[];
};

export type BacktestBenchmark = {
  key: string;
  label: string;
  symbol: string | null;
  metrics: BacktestMetrics;
  equity_curve: BacktestEquityPoint[];
};

export type BacktestDataNote = {
  severity: "info" | "warning" | "error";
  message: string;
};

export type BacktestRiskSummary = {
  average_target_exposure: number | null;
  average_realized_exposure: number | null;
  average_cash_weight: number | null;
  risk_off_rebalance_count: number;
  constrained_rebalance_count: number;
  data_notes: string[];
};

export type BacktestResult = {
  config: BacktestConfig;
  metrics: BacktestMetrics;
  equity_curve: BacktestEquityPoint[];
  benchmarks: BacktestBenchmark[];
  holdings: BacktestHoldingSnapshot[];
  risk_summary: BacktestRiskSummary | null;
  data_notes: BacktestDataNote[];
};

export type WalkForwardConfig = {
  train_months: number;
  test_months: number;
  step_months: number;
  top_n: number;
  cost_bps: number;
};

export type WalkForwardWindow = {
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  selected_factors: string[];
  factor_weights: Record<string, number>;
  train_icir: Record<string, number | null>;
  test_metrics: BacktestMetrics;
  test_equity_curve: BacktestEquityPoint[];
};

export type WalkForwardResult = {
  config: WalkForwardConfig;
  windows: WalkForwardWindow[];
  oos_equity_curve: BacktestEquityPoint[];
  oos_metrics: BacktestMetrics;
  is_metrics: BacktestMetrics;
  factor_stability: number;
  weight_stability: Record<string, number | null>;
  overfit_warning: string;
  data_notes: string[];
  generated_at: string | null;
};

export type SignalSnapshotResult = {
  ok: boolean;
  date: string | null;
  rows: number;
  message: string;
};

export type SignalPerformance = {
  snapshot_date: string;
  horizon_days: number;
  top_mean_return: number;
  benchmark_return: number;
  excess_return: number;
  hit_rate: number;
  score_return_corr: number | null;
  top_symbols: string[];
  data_notes: string[];
};

export type MonitoringCheck = {
  key: string;
  label: string;
  status: "ok" | "watch" | "alert" | "missing";
  value: string;
  detail: string;
};

export type MonitoringReport = {
  generated_at: string;
  market_regime: MarketRegimeSnapshot | null;
  checks: MonitoringCheck[];
  alerts: string[];
  data_notes: string[];
};
