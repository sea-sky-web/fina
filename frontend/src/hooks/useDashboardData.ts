import { useCallback, useRef, useState } from "react";

import {
  fetchDataStatus,
  fetchEtfs,
  fetchFactorDefinitions,
  fetchResearchSignals,
} from "../api/client";
import { ETF_UNIVERSE_LIMIT } from "../constants/research";
import type { DataStatus, EtfBasic, FactorDefinition, ResearchSignal } from "../types/etf";

type DashboardLoadResult = {
  statuses: DataStatus[];
  etfs: EtfBasic[];
  factorDefinitions: FactorDefinition[];
  researchSignals: ResearchSignal[];
  selectedSymbol: string | null;
};

export function useDashboardData() {
  const [statuses, setStatuses] = useState<DataStatus[]>([]);
  const [etfs, setEtfs] = useState<EtfBasic[]>([]);
  const [factorDefinitions, setFactorDefinitions] = useState<FactorDefinition[]>([]);
  const [researchSignals, setResearchSignals] = useState<ResearchSignal[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const loadRequestRef = useRef(0);

  const loadDashboardData = useCallback(
    async (preferredSymbol?: string | null): Promise<DashboardLoadResult | null> => {
      const requestId = loadRequestRef.current + 1;
      loadRequestRef.current = requestId;

      const [statusData, etfData, definitions, signalData] = await Promise.all([
        fetchDataStatus(),
        fetchEtfs(ETF_UNIVERSE_LIMIT),
        fetchFactorDefinitions(),
        fetchResearchSignals(ETF_UNIVERSE_LIMIT),
      ]);

      if (requestId !== loadRequestRef.current) {
        return null;
      }

      const nextSymbol =
        preferredSymbol && etfData.some((item) => item.symbol === preferredSymbol)
          ? preferredSymbol
          : (signalData[0]?.symbol ?? etfData[0]?.symbol ?? null);

      setStatuses(statusData);
      setEtfs(etfData);
      setFactorDefinitions(definitions);
      setResearchSignals(signalData);
      setSelectedSymbol(nextSymbol);

      return {
        statuses: statusData,
        etfs: etfData,
        factorDefinitions: definitions,
        researchSignals: signalData,
        selectedSymbol: nextSymbol,
      };
    },
    []
  );

  return {
    statuses,
    setStatuses,
    etfs,
    factorDefinitions,
    researchSignals,
    setResearchSignals,
    selectedSymbol,
    setSelectedSymbol,
    loadDashboardData,
  };
}
