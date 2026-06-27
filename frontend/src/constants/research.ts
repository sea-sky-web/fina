export const ETF_UNIVERSE_LIMIT = 100;
export const ALL_THEMES = "全部";
export const DEFAULT_FACTOR = "momentum_60d";

export type Workspace = "monitor" | "factors" | "strategy" | "data";

export const WORKSPACES: Array<{ key: Workspace; label: string; meta: string }> = [
  { key: "monitor", label: "决策看板", meta: "PRICE / SIGNAL / RANK" },
  { key: "factors", label: "因子研究", meta: "EVAL / DIAG / RANK" },
  { key: "strategy", label: "策略验证", meta: "BACKTEST / WF / OOS" },
  { key: "data", label: "数据健康", meta: "STATUS / REVIEW" },
];

export type StrategyParams = {
  topN: number;
  costBps: number;
};

export const DEFAULT_STRATEGY_PARAMS: StrategyParams = {
  topN: 10,
  costBps: 5,
};
