import { useCallback, useEffect, useRef, useState } from "react";

import { fetchSignalPerformance } from "../api/client";
import type { SignalPerformance } from "../types/etf";

type UseSignalPerformanceOptions = {
  enabled: boolean;
};

export function useSignalPerformance({ enabled }: UseSignalPerformanceOptions) {
  const [signalPerformance, setSignalPerformance] = useState<SignalPerformance[]>([]);
  const [hasLoadedSignalPerformance, setHasLoadedSignalPerformance] = useState(false);
  const requestRef = useRef(0);

  const refreshSignalPerformance = useCallback(async () => {
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    try {
      const performance = await fetchSignalPerformance();
      if (requestId === requestRef.current) {
        setSignalPerformance(performance);
        setHasLoadedSignalPerformance(true);
      }
    } catch {
      if (requestId === requestRef.current) {
        setSignalPerformance([]);
        setHasLoadedSignalPerformance(true);
      }
    }
  }, []);

  useEffect(() => {
    if (!enabled || hasLoadedSignalPerformance) {
      return;
    }
    void refreshSignalPerformance();
  }, [enabled, hasLoadedSignalPerformance, refreshSignalPerformance]);

  return {
    signalPerformance,
    refreshSignalPerformance,
  };
}
