import { useEffect, useRef, useState } from "react";

import { fetchEtfDaily, fetchFactorHistory, fetchResearchSignal } from "../api/client";
import type { EtfDailyBar, FactorHistoryPoint, ResearchSignal } from "../types/etf";

type UseSelectedEtfDataOptions = {
  onError?: (message: string) => void;
};

function requestMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function useSelectedEtfData(
  selectedSymbol: string | null,
  activeFactor: string,
  { onError }: UseSelectedEtfDataOptions = {}
) {
  const [bars, setBars] = useState<EtfDailyBar[]>([]);
  const [selectedSignal, setSelectedSignal] = useState<ResearchSignal | null>(null);
  const [factorHistory, setFactorHistory] = useState<FactorHistoryPoint[]>([]);
  const detailRequestRef = useRef(0);
  const historyRequestRef = useRef(0);

  useEffect(() => {
    const requestId = detailRequestRef.current + 1;
    detailRequestRef.current = requestId;

    if (!selectedSymbol) {
      setBars([]);
      setSelectedSignal(null);
      return;
    }

    async function loadSelectedData(symbol: string) {
      try {
        const [dailyData, signalDetail] = await Promise.all([
          fetchEtfDaily(symbol),
          fetchResearchSignal(symbol).catch(() => null),
        ]);
        if (requestId !== detailRequestRef.current) {
          return;
        }
        setBars(dailyData);
        setSelectedSignal(signalDetail);
      } catch (error) {
        if (requestId !== detailRequestRef.current) {
          return;
        }
        setBars([]);
        setSelectedSignal(null);
        onError?.(requestMessage(error, "行情加载失败"));
      }
    }

    void loadSelectedData(selectedSymbol);
  }, [onError, selectedSymbol]);

  useEffect(() => {
    const requestId = historyRequestRef.current + 1;
    historyRequestRef.current = requestId;

    if (!selectedSymbol) {
      setFactorHistory([]);
      return;
    }

    async function loadHistory(symbol: string, factorName: string) {
      try {
        const history = await fetchFactorHistory(symbol, factorName);
        if (requestId === historyRequestRef.current) {
          setFactorHistory(history);
        }
      } catch {
        if (requestId === historyRequestRef.current) {
          setFactorHistory([]);
        }
      }
    }

    void loadHistory(selectedSymbol, activeFactor);
  }, [activeFactor, selectedSymbol]);

  return {
    bars,
    selectedSignal,
    factorHistory,
  };
}
