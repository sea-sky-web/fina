import { useCallback, useEffect, useRef, useState } from "react";

import { fetchMonitoringReport } from "../api/client";
import type { MonitoringReport } from "../types/etf";

type UseMonitoringReportOptions = {
  enabled: boolean;
  pollMs?: number;
  onError?: (message: string) => void;
};

export function useMonitoringReport({
  enabled,
  pollMs = 60000,
  onError,
}: UseMonitoringReportOptions) {
  const [monitoringReport, setMonitoringReport] = useState<MonitoringReport | null>(null);
  const [isMonitoringLoading, setIsMonitoringLoading] = useState(false);
  const requestRef = useRef(0);

  const refreshMonitoringReport = useCallback(async () => {
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    setIsMonitoringLoading(true);
    try {
      const report = await fetchMonitoringReport();
      if (requestId === requestRef.current) {
        setMonitoringReport(report);
      }
    } catch (error) {
      if (requestId === requestRef.current) {
        onError?.(error instanceof Error ? error.message : "监控报告加载失败");
      }
    } finally {
      if (requestId === requestRef.current) {
        setIsMonitoringLoading(false);
      }
    }
  }, [onError]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    void refreshMonitoringReport();
    const timer = window.setInterval(() => {
      void refreshMonitoringReport();
    }, pollMs);
    return () => window.clearInterval(timer);
  }, [enabled, pollMs, refreshMonitoringReport]);

  return {
    monitoringReport,
    isMonitoringLoading,
    refreshMonitoringReport,
  };
}
