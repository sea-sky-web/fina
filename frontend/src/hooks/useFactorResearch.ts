import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchFactorDiagnostics,
  fetchFactorEvaluationReport,
  fetchFactorPoolEvaluationReport,
  fetchFactorScores,
} from "../api/client";
import { ETF_UNIVERSE_LIMIT } from "../constants/research";
import type {
  FactorDiagnostics,
  FactorEvaluationReport,
  FactorPoolEvaluationReport,
  FactorScore,
} from "../types/etf";

type UseFactorResearchOptions = {
  shouldLoadEvaluation: boolean;
  onError?: (message: string) => void;
};

function requestMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function useFactorResearch(
  activeFactor: string,
  { shouldLoadEvaluation, onError }: UseFactorResearchOptions
) {
  const [factorScores, setFactorScores] = useState<FactorScore[]>([]);
  const [factorDiagnostics, setFactorDiagnostics] = useState<FactorDiagnostics | null>(null);
  const [factorEvaluation, setFactorEvaluation] = useState<FactorEvaluationReport | null>(null);
  const [factorPoolEvaluation, setFactorPoolEvaluation] =
    useState<FactorPoolEvaluationReport | null>(null);
  const [isDiagnosticsLoading, setIsDiagnosticsLoading] = useState(false);
  const [isEvaluationLoading, setIsEvaluationLoading] = useState(false);
  const scoresRequestRef = useRef(0);
  const evaluationRequestRef = useRef(0);

  const loadFactorScores = useCallback(
    async (factorName = activeFactor) => {
      const requestId = scoresRequestRef.current + 1;
      scoresRequestRef.current = requestId;
      try {
        const scores = await fetchFactorScores(factorName, ETF_UNIVERSE_LIMIT);
        if (requestId === scoresRequestRef.current) {
          setFactorScores(scores);
        }
      } catch (error) {
        if (requestId === scoresRequestRef.current) {
          setFactorScores([]);
          onError?.(requestMessage(error, "因子加载失败"));
        }
      }
    },
    [activeFactor, onError]
  );

  const loadEvaluation = useCallback(
    async (factorName = activeFactor) => {
      const requestId = evaluationRequestRef.current + 1;
      evaluationRequestRef.current = requestId;
      setIsDiagnosticsLoading(true);
      setIsEvaluationLoading(true);

      const [diagnosticsResult, reportResult, poolResult] = await Promise.allSettled([
        fetchFactorDiagnostics(factorName),
        fetchFactorEvaluationReport(factorName),
        fetchFactorPoolEvaluationReport(),
      ]);

      if (requestId !== evaluationRequestRef.current) {
        return;
      }

      setFactorDiagnostics(
        diagnosticsResult.status === "fulfilled" ? diagnosticsResult.value : null
      );
      setFactorEvaluation(reportResult.status === "fulfilled" ? reportResult.value : null);
      setFactorPoolEvaluation(poolResult.status === "fulfilled" ? poolResult.value : null);
      setIsDiagnosticsLoading(false);
      setIsEvaluationLoading(false);
    },
    [activeFactor]
  );

  useEffect(() => {
    void loadFactorScores(activeFactor);
  }, [activeFactor, loadFactorScores]);

  useEffect(() => {
    if (!shouldLoadEvaluation) {
      return;
    }
    void loadEvaluation(activeFactor);
  }, [activeFactor, loadEvaluation, shouldLoadEvaluation]);

  const refreshFactorResearch = useCallback(async () => {
    await loadFactorScores(activeFactor);
    if (shouldLoadEvaluation) {
      await loadEvaluation(activeFactor);
    }
  }, [activeFactor, loadEvaluation, loadFactorScores, shouldLoadEvaluation]);

  return {
    factorScores,
    factorDiagnostics,
    factorEvaluation,
    factorPoolEvaluation,
    isDiagnosticsLoading,
    isEvaluationLoading,
    loadEvaluation,
    refreshFactorResearch,
  };
}
