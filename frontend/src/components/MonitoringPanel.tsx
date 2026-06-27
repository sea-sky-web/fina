import { Activity, AlertTriangle, RefreshCw, ShieldCheck } from "lucide-react";

import type { MonitoringCheck, MonitoringReport } from "../types/etf";

type MonitoringPanelProps = {
  report: MonitoringReport | null;
  isLoading: boolean;
  onRefresh: () => void;
};

function formatPercent(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return `${(value * 100).toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })}%`;
}

function checkClass(status: MonitoringCheck["status"]) {
  if (status === "ok") return "ok";
  if (status === "alert") return "alert";
  return "watch";
}

export function MonitoringPanel({ report, isLoading, onRefresh }: MonitoringPanelProps) {
  const regime = report?.market_regime ?? null;

  return (
    <section className="section monitoringSection">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">CONTINUOUS MONITORING</p>
          <h2>风险与信号健康监控</h2>
        </div>
        <div className="sectionActions">
          <span className="sectionMeta">
            {report ? new Date(report.generated_at).toLocaleTimeString("zh-CN") : "not loaded"}
          </span>
          <button className="sectionActionButton" disabled={isLoading} onClick={onRefresh} type="button">
            <RefreshCw className={isLoading ? "spin" : ""} size={13} />
            刷新
          </button>
        </div>
      </div>

      <div className="monitoringGrid">
        <div className="monitoringRegime">
          <h3>
            <ShieldCheck size={15} />
            市场状态
          </h3>
          <strong>{regime?.label_zh ?? "-"}</strong>
          <dl>
            <dt>目标暴露</dt>
            <dd>{formatPercent(regime?.target_exposure)}</dd>
            <dt>趋势分</dt>
            <dd>{formatPercent(regime?.trend_score, 2)}</dd>
            <dt>年化波动</dt>
            <dd>{formatPercent(regime?.volatility_annualized, 1)}</dd>
            <dt>回撤</dt>
            <dd>{formatPercent(regime?.drawdown, 1)}</dd>
          </dl>
        </div>

        <div className="monitoringChecks">
          {report ? (
            report.checks.map((check) => (
              <div className={`monitoringCheck ${checkClass(check.status)}`} key={check.key}>
                <span>
                  {check.status === "ok" ? <Activity size={14} /> : <AlertTriangle size={14} />}
                  {check.label}
                </span>
                <strong>{check.value}</strong>
                <p>{check.detail}</p>
              </div>
            ))
          ) : (
            <div className="backtestEmpty small">监控报告尚未加载</div>
          )}
        </div>
      </div>

      {report && report.alerts.length > 0 ? (
        <div className="monitoringAlerts">
          {report.alerts.map((alert) => (
            <p key={alert}>{alert}</p>
          ))}
        </div>
      ) : null}
    </section>
  );
}
