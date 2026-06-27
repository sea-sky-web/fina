import { useCallback, useMemo, useRef, useState } from "react";

import { fetchResearchSignalBacktest, fetchWalkForward } from "../api/client";
import { DEFAULT_STRATEGY_PARAMS, type StrategyParams } from "../constants/research";
import type { BacktestResult, WalkForwardResult } from "../types/etf";

type UseStrategyValidationOptions = {
  onError?: (message: string) => void;
};

function requestMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function sameParams(left: StrategyParams | null, right: StrategyParams) {
  return left?.topN === right.topN && left.costBps === right.costBps;
}

export function useStrategyValidation({ onError }: UseStrategyValidationOptions = {}) {
  const [params, setParams] = useState<StrategyParams>(DEFAULT_STRATEGY_PARAMS);
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);
  const [walkForwardResult, setWalkForwardResult] = useState<WalkForwardResult | null>(null);
  const [isBacktestLoading, setIsBacktestLoading] = useState(false);
  const [isWalkForwardLoading, setIsWalkForwardLoading] = useState(false);
  const [lastBacktestParams, setLastBacktestParams] = useState<StrategyParams | null>(null);
  const [lastWalkForwardParams, setLastWalkForwardParams] = useState<StrategyParams | null>(null);
  const backtestRequestRef = useRef(0);
  const walkForwardRequestRef = useRef(0);

  const setTopN = useCallback((topN: number) => {
    setParams((current) => ({ ...current, topN }));
  }, []);

  const setCostBps = useCallback((costBps: number) => {
    setParams((current) => ({ ...current, costBps }));
  }, []);

  const runBacktest = useCallback(async () => {
    const requestParams = { ...params };
    const requestId = backtestRequestRef.current + 1;
    backtestRequestRef.current = requestId;
    setIsBacktestLoading(true);
    try {
      const result = await fetchResearchSignalBacktest(requestParams);
      if (requestId === backtestRequestRef.current) {
        setBacktestResult(result);
        setLastBacktestParams(requestParams);
      }
    } catch (error) {
      if (requestId === backtestRequestRef.current) {
        setBacktestResult(null);
        onError?.(requestMessage(error, "策略验证加载失败"));
      }
    } finally {
      if (requestId === backtestRequestRef.current) {
        setIsBacktestLoading(false);
      }
    }
  }, [onError, params]);

  const runWalkForward = useCallback(async () => {
    const requestParams = { ...params };
    const requestId = walkForwardRequestRef.current + 1;
    walkForwardRequestRef.current = requestId;
    setIsWalkForwardLoading(true);
    try {
      const result = await fetchWalkForward(requestParams);
      if (requestId === walkForwardRequestRef.current) {
        setWalkForwardResult(result);
        setLastWalkForwardParams(requestParams);
      }
    } catch {
      if (requestId === walkForwardRequestRef.current) {
        setWalkForwardResult(null);
      }
    } finally {
      if (requestId === walkForwardRequestRef.current) {
        setIsWalkForwardLoading(false);
      }
    }
  }, [params]);

  const isBacktestStale = useMemo(
    () => Boolean(backtestResult && !sameParams(lastBacktestParams, params)),
    [backtestResult, lastBacktestParams, params]
  );
  const isWalkForwardStale = useMemo(
    () => Boolean(walkForwardResult && !sameParams(lastWalkForwardParams, params)),
    [lastWalkForwardParams, params, walkForwardResult]
  );

  return {
    backtestTopN: params.topN,
    backtestCostBps: params.costBps,
    setBacktestTopN: setTopN,
    setBacktestCostBps: setCostBps,
    backtestResult,
    walkForwardResult,
    isBacktestLoading,
    isWalkForwardLoading,
    isBacktestStale,
    isWalkForwardStale,
    runBacktest,
    runWalkForward,
  };
}
