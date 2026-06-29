import { History, Save } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { refreshTopEtfs, takeSignalSnapshot } from "../api/client";
import { BacktestPanel } from "../components/BacktestPanel";
import { EtfTable } from "../components/EtfTable";
import { FactorDiagnosticsPanel } from "../components/FactorDiagnosticsPanel";
import { FactorEvaluationPanel } from "../components/FactorEvaluationPanel";
import { FactorPanel } from "../components/FactorPanel";
import { MonitoringPanel } from "../components/MonitoringPanel";
import { PriceChart } from "../components/PriceChart";
import { SignalPanel } from "../components/SignalPanel";
import { StatusPanel } from "../components/StatusPanel";
import { WalkForwardPanel } from "../components/WalkForwardPanel";
import {
  ALL_THEMES,
  DEFAULT_FACTOR,
  ETF_UNIVERSE_LIMIT,
  WORKSPACES,
  type Workspace,
} from "../constants/research";
import { useDashboardData } from "../hooks/useDashboardData";
import { useFactorResearch } from "../hooks/useFactorResearch";
import { useMonitoringReport } from "../hooks/useMonitoringReport";
import { useSelectedEtfData } from "../hooks/useSelectedEtfData";
import { useSignalPerformance } from "../hooks/useSignalPerformance";
import { useStrategyValidation } from "../hooks/useStrategyValidation";

export function App() {
  const [activeFactor, setActiveFactor] = useState(DEFAULT_FACTOR);
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace>("monitor");
  const [activeTheme, setActiveTheme] = useState(ALL_THEMES);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSnapshotting, setIsSnapshotting] = useState(false);
  const [snapshotToast, setSnapshotToast] = useState<string | null>(null);

  const handleRequestError = useCallback((message: string) => {
    setError(message);
  }, []);

  const {
    statuses,
    etfs,
    factorDefinitions,
    researchSignals,
    selectedSymbol,
    setSelectedSymbol,
    loadDashboardData,
  } = useDashboardData();
  const { bars, selectedSignal, factorHistory } = useSelectedEtfData(
    selectedSymbol,
    activeFactor,
    { onError: handleRequestError }
  );
  const {
    factorScores,
    factorDiagnostics,
    factorEvaluation,
    factorPoolEvaluation,
    isDiagnosticsLoading,
    isEvaluationLoading,
    refreshFactorResearch,
  } = useFactorResearch(activeFactor, {
    shouldLoadEvaluation: activeWorkspace === "factors",
    onError: handleRequestError,
  });
  const {
    backtestTopN,
    backtestCostBps,
    setBacktestTopN,
    setBacktestCostBps,
    backtestResult,
    walkForwardResult,
    isBacktestLoading,
    isWalkForwardLoading,
    isBacktestStale,
    isWalkForwardStale,
    runBacktest,
    runWalkForward,
  } = useStrategyValidation({ onError: handleRequestError });
  const { signalPerformance, refreshSignalPerformance } = useSignalPerformance({
    enabled: activeWorkspace === "data",
  });
  const { monitoringReport, isMonitoringLoading, refreshMonitoringReport } = useMonitoringReport({
    enabled: activeWorkspace === "data",
    onError: handleRequestError,
  });

  useEffect(() => {
    async function loadInitialData() {
      try {
        await loadDashboardData();
      } catch (requestError) {
        setError(requestError instanceof Error ? requestError.message : "数据加载失败");
      }
    }

    void loadInitialData();
  }, [loadDashboardData]);

  const themeOptions = useMemo(() => {
    const counts = new Map<string, number>();
    etfs.forEach((item) => counts.set(item.theme, (counts.get(item.theme) ?? 0) + 1));
    const options = Array.from(counts.entries())
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0], "zh-CN"))
      .map(([theme, count]) => ({ theme, count }));
    return [{ theme: ALL_THEMES, count: etfs.length }, ...options];
  }, [etfs]);

  const filteredEtfs = useMemo(() => {
    if (activeTheme === ALL_THEMES) {
      return etfs;
    }
    return etfs.filter((item) => item.theme === activeTheme);
  }, [activeTheme, etfs]);

  const filteredFactorScores = useMemo(() => {
    if (activeTheme === ALL_THEMES) {
      return factorScores;
    }
    return factorScores.filter((item) => item.theme === activeTheme);
  }, [activeTheme, factorScores]);

  const filteredResearchSignals = useMemo(() => {
    if (activeTheme === ALL_THEMES) {
      return researchSignals;
    }
    return researchSignals.filter((item) => item.theme === activeTheme);
  }, [activeTheme, researchSignals]);

  useEffect(() => {
    if (filteredEtfs.length === 0) {
      setSelectedSymbol(null);
      return;
    }
    if (!selectedSymbol || !filteredEtfs.some((item) => item.symbol === selectedSymbol)) {
      const filteredSymbols = new Set(filteredEtfs.map((item) => item.symbol));
      const signalSymbol = filteredResearchSignals.find((item) => filteredSymbols.has(item.symbol))?.symbol;
      setSelectedSymbol(signalSymbol ?? filteredEtfs[0].symbol);
    }
  }, [filteredEtfs, filteredResearchSignals, selectedSymbol, setSelectedSymbol]);

  function handleFactorChange(name: string) {
    setActiveFactor(name);
  }

  async function handleRefresh() {
    setIsRefreshing(true);
    setError(null);
    setNotice(`正在重新采集 Top ${ETF_UNIVERSE_LIMIT} ETF 数据...`);
    try {
      const result = await refreshTopEtfs(ETF_UNIVERSE_LIMIT, 365);
      await loadDashboardData(selectedSymbol);
      await refreshFactorResearch();
      if (activeWorkspace === "data") {
        await refreshSignalPerformance();
        await refreshMonitoringReport();
      }
      setNotice(
        result.ok
          ? `${result.message} ${result.selected_rows} 只 ETF，${result.daily_rows.toLocaleString("zh-CN")} 条日线，${result.factor_rows.toLocaleString("zh-CN")} 条因子。`
          : null
      );
      if (!result.ok) {
        setError(result.message);
      }
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "刷新失败";
      setError(`${message}；已保留上一次成功采集的数据。`);
      setNotice(null);
      try {
        await loadDashboardData(selectedSymbol);
        await refreshFactorResearch();
      } catch {
        // Keep the original refresh error visible.
      }
    } finally {
      setIsRefreshing(false);
    }
  }

  async function handleSnapshot() {
    setIsSnapshotting(true);
    try {
      const result = await takeSignalSnapshot(20);
      if (result.ok) {
        const msg = `快照已保存: ${result.date}, ${result.rows} 只 ETF`;
        setSnapshotToast(msg);
        setTimeout(() => setSnapshotToast(null), 3500);
        await refreshSignalPerformance();
        await refreshMonitoringReport();
      } else {
        setError(result.message);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "快照保存失败");
    } finally {
      setIsSnapshotting(false);
    }
  }

  const latestUpdate = useMemo(() => {
    const values = statuses.map((item) => item.last_success_at).filter(Boolean);
    return values[0] ?? "暂无采集记录";
  }, [statuses]);

  const tickerStrip = useMemo(() => filteredEtfs.slice(0, 6), [filteredEtfs]);
  const latestTradeDate = useMemo(() => {
    const dates = statuses.map((item) => item.last_trade_date).filter(Boolean);
    return dates[0] ?? "-";
  }, [statuses]);
  const activeFactorDefinition = useMemo(
    () => factorDefinitions.find((definition) => definition.name === activeFactor),
    [activeFactor, factorDefinitions]
  );

  const dataHealth = useMemo(() => {
    if (statuses.length === 0) return { label: "未初始化", cls: "healthDim" as const, hint: "等待首次数据加载" };
    const okCount = statuses.filter((s) => s.status === "ok").length;
    const staleCount = statuses.filter((s) => s.status === "stale").length;
    const errCount = statuses.filter((s) => s.status === "error" || s.status === "empty").length;
    if (errCount > 0) return { label: "无数据", cls: "healthBad" as const, hint: "请点击刷新数据采集 ETF 行情" };
    if (staleCount > 0) return { label: "数据过期", cls: "healthWarn" as const, hint: `${staleCount} 个数据集需要刷新` };
    return { label: "数据正常", cls: "healthOk" as const, hint: `${okCount} 个数据集最新` };
  }, [statuses]);

  const factorHealth = useMemo(() => {
    if (isEvaluationLoading) return { label: "评估加载中", cls: "healthDim" as const, hint: "正在加载因子池评估报告..." };
    if (!factorPoolEvaluation) return { label: "待评估", cls: "healthDim" as const, hint: "进入因子研究页后加载评估报告" };
    if (factorPoolEvaluation.pool_health === "健康") return { label: "因子池健康", cls: "healthOk" as const, hint: "因子间相关性合理" };
    if (factorPoolEvaluation.pool_health === "冗余") return { label: "因子冗余", cls: "healthWarn" as const, hint: "部分因子高度相关，建议筛选" };
    return { label: "因子不足", cls: "healthBad" as const, hint: "通过质量门槛的因子太少" };
  }, [factorPoolEvaluation, isEvaluationLoading]);

  const wfHealth = useMemo(() => {
    if (isWalkForwardLoading) return { label: "WF计算中", cls: "healthDim" as const, hint: "正在运行滚动窗口验证..." };
    if (!walkForwardResult) return { label: "WF待运行", cls: "healthDim" as const, hint: "进入策略验证页后手动运行" };
    if (walkForwardResult.windows.length === 0) return { label: "WF无窗口", cls: "healthDim" as const, hint: "数据不足以划分训练/测试窗口" };
    if (walkForwardResult.overfit_warning.includes("严重过拟合")) return { label: "严重过拟合", cls: "healthBad" as const, hint: "样本外收益远低于样本内" };
    if (walkForwardResult.overfit_warning.includes("轻微")) return { label: "轻微过拟合", cls: "healthWarn" as const, hint: "样本外表现弱于样本内" };
    return { label: "WF正常", cls: "healthOk" as const, hint: "样本内外表现一致" };
  }, [isWalkForwardLoading, walkForwardResult]);

  return (
    <main className="appShell">
      <header className="topbar">
        <div>
          <p className="eyebrow">ETF RESEARCH TERMINAL</p>
          <h1>沪深 ETF 因子决策研究台</h1>
          <div className="topHealth">
            <span className={`healthDot ${dataHealth.cls}`} title={dataHealth.hint}>
              数据 {dataHealth.label}
              {dataHealth.cls === "healthDim" ? <span className="healthHint">— {dataHealth.hint}</span> : null}
            </span>
            <span className={`healthDot ${factorHealth.cls}`} title={factorHealth.hint}>
              因子 {factorHealth.label}
              {factorHealth.cls === "healthDim" ? <span className="healthHint">— {factorHealth.hint}</span> : null}
            </span>
            <span className={`healthDot ${wfHealth.cls}`} title={wfHealth.hint}>
              验证 {wfHealth.label}
              {wfHealth.cls === "healthDim" ? <span className="healthHint">— {wfHealth.hint}</span> : null}
            </span>
          </div>
        </div>
        <div className="terminalStats">
          <span>
            SYMBOL
            <strong>{selectedSymbol ?? "-"}</strong>
          </span>
          <span>
            SIGNAL
            <strong>{selectedSignal ? `${selectedSignal.research_score.toFixed(1)}分` : "-"}</strong>
          </span>
          <span>
            TRADE DATE
            <strong>{latestTradeDate}</strong>
          </span>
          <span>
            LAST UPDATE
            <strong>{latestUpdate}</strong>
          </span>
        </div>
      </header>

      <div className="tickerStrip">
        {tickerStrip.map((item) => (
          <button
            className={`tickerItem ${item.symbol === selectedSymbol ? "active" : ""}`}
            key={item.symbol}
            onClick={() => setSelectedSymbol(item.symbol)}
            type="button"
          >
            <span>{item.symbol}</span>
            <strong>{item.latest_price?.toFixed(3) ?? "-"}</strong>
            <em className={(item.pct_chg ?? 0) >= 0 ? "positive" : "negative"}>
              {item.pct_chg === null ? "-" : `${item.pct_chg.toFixed(2)}%`}
            </em>
          </button>
        ))}
      </div>

      {error ? <div className="errorBanner" onClick={() => setError(null)}>{error}</div> : null}
      {notice ? <div className="noticeBanner">{notice}</div> : null}

      <div className="quickActions">
        <button disabled={isRefreshing} onClick={handleRefresh} title="重新采集 ETF 数据" type="button">
          <History size={14} />
          {isRefreshing ? "刷新中..." : "刷新数据"}
        </button>
        <button disabled={isSnapshotting || researchSignals.length === 0} onClick={handleSnapshot} title="保存当前信号快照以便日后复盘" type="button">
          <Save size={14} />
          {isSnapshotting ? "保存中..." : "保存快照"}
        </button>
        <span className="actionDivider" />
        <span className="actionHint">
          切换工作区开始研究 → 保存快照记录信号 → 数据健康页查看复盘
        </span>
      </div>

      <nav className="workspaceTabs" aria-label="研究工作区">
        {WORKSPACES.map((workspace) => (
          <button
            className={workspace.key === activeWorkspace ? "active" : ""}
            key={workspace.key}
            onClick={() => setActiveWorkspace(workspace.key)}
            type="button"
          >
            <strong>{workspace.label}</strong>
            <span>{workspace.meta}</span>
          </button>
        ))}
      </nav>

      {activeWorkspace === "monitor" ? (
        <div className="workspacePanel">
          <div className="dashboardGrid">
            <EtfTable
              activeTheme={activeTheme}
              etfs={filteredEtfs}
              onSelect={setSelectedSymbol}
              onThemeChange={setActiveTheme}
              selectedSymbol={selectedSymbol}
              themeOptions={themeOptions}
              totalCount={etfs.length}
            />
            <PriceChart
              activeFactor={activeFactor}
              bars={bars}
              factorDefinition={activeFactorDefinition}
              factorHistory={factorHistory}
              factorLabel={activeFactorDefinition?.label ?? activeFactor}
              symbol={selectedSymbol}
            />
          </div>
          <SignalPanel
            activeTheme={activeTheme}
            definitions={factorDefinitions}
            onSelect={setSelectedSymbol}
            selectedSignal={selectedSignal}
            selectedSymbol={selectedSymbol}
            signals={filteredResearchSignals}
          />
        </div>
      ) : null}

      {activeWorkspace === "factors" ? (
        <div className="workspacePanel factorWorkspace">
          <FactorEvaluationPanel
            definitions={factorDefinitions}
            isLoading={isEvaluationLoading}
            poolReport={factorPoolEvaluation}
            report={factorEvaluation}
          />
          <FactorDiagnosticsPanel
            diagnostics={factorDiagnostics}
            isLoading={isDiagnosticsLoading}
            onSelect={setSelectedSymbol}
            selectedSymbol={selectedSymbol}
          />
          <FactorPanel
            activeFactor={activeFactor}
            activeTheme={activeTheme}
            definitions={factorDefinitions}
            onFactorChange={handleFactorChange}
            onSelect={setSelectedSymbol}
            scores={filteredFactorScores}
            selectedSymbol={selectedSymbol}
          />
        </div>
      ) : null}

      {activeWorkspace === "strategy" ? (
        <div className="workspacePanel">
          <BacktestPanel
            costBps={backtestCostBps}
            isLoading={isBacktestLoading}
            isStale={isBacktestStale}
            onCostBpsChange={setBacktestCostBps}
            onRun={runBacktest}
            onSelect={setSelectedSymbol}
            onTopNChange={setBacktestTopN}
            result={backtestResult}
            topN={backtestTopN}
          />
          <WalkForwardPanel
            isLoading={isWalkForwardLoading}
            isStale={isWalkForwardStale}
            onRun={runWalkForward}
            result={walkForwardResult}
          />
        </div>
      ) : null}

      {activeWorkspace === "data" ? (
        <div className="workspacePanel dataWorkspace">
          <MonitoringPanel
            isLoading={isMonitoringLoading}
            onRefresh={refreshMonitoringReport}
            report={monitoringReport}
          />
          <StatusPanel isRefreshing={isRefreshing} onRefresh={handleRefresh} statuses={statuses} />
          {signalPerformance.length > 0 ? (
            <section className="section">
              <div className="sectionHeader">
                <div>
                  <p className="eyebrow">SIGNAL REVIEW</p>
                  <h2>信号复盘</h2>
                </div>
                <span className="sectionMeta">
                  {signalPerformance.length} snapshots reviewed
                </span>
              </div>
              <div className="tableWrap">
                <table>
                  <thead>
                    <tr>
                      <th>快照日期</th>
                      <th>前瞻天数</th>
                      <th>Top 平均收益</th>
                      <th>基准收益</th>
                      <th>超额</th>
                      <th>胜率</th>
                      <th>分数-收益相关</th>
                    </tr>
                  </thead>
                  <tbody>
                    {signalPerformance.map((perf) => (
                      <tr key={perf.snapshot_date}>
                        <td>{perf.snapshot_date}</td>
                        <td>{perf.horizon_days}d</td>
                        <td className={(perf.top_mean_return ?? 0) >= 0 ? "positive" : "negative"}>
                          {(perf.top_mean_return * 100).toFixed(2)}%
                        </td>
                        <td className={(perf.benchmark_return ?? 0) >= 0 ? "positive" : "negative"}>
                          {(perf.benchmark_return * 100).toFixed(2)}%
                        </td>
                        <td className={(perf.excess_return ?? 0) >= 0 ? "positive" : "negative"}>
                          {(perf.excess_return * 100).toFixed(2)}%
                        </td>
                        <td>{(perf.hit_rate * 100).toFixed(0)}%</td>
                        <td>
                          {perf.score_return_corr !== null
                            ? perf.score_return_corr.toFixed(3)
                            : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}
          <section className="section dataRuleSection">
            <div className="sectionHeader">
              <div>
                <p className="eyebrow">DATA POLICY</p>
                <h2>数据与研究约束</h2>
              </div>
              <span className="sectionMeta">local parquet / akshare</span>
            </div>
            <div className="dataRules">
              <p>刷新失败时保留上一份可用清洗数据，页面必须显示异常说明。</p>
              <p>回测使用本地日线和因子结果即时计算，不写入新的持久化回测文件。</p>
              <p>Walk-forward 在每个窗口内独立训练权重，做纯样本外验证。</p>
              <p>所有信号、诊断和策略验证仅用于历史研究，不输出交易动作。</p>
            </div>
          </section>
        </div>
      ) : null}

      {snapshotToast ? <div className="snapshotToast">{snapshotToast}</div> : null}
    </main>
  );
}
