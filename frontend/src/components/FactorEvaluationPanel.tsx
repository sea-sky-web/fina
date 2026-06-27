import { Fragment } from "react";
import { Activity, AlertTriangle, GitCompare, Grid3X3, TrendingUp } from "lucide-react";

import type {
  FactorDefinition,
  FactorEvaluationReport,
  FactorPoolEvaluationReport,
} from "../types/etf";

type FactorEvaluationPanelProps = {
  definitions: FactorDefinition[];
  isLoading: boolean;
  poolReport: FactorPoolEvaluationReport | null;
  report: FactorEvaluationReport | null;
};

function formatNumber(value: number | null | undefined, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: Math.abs(value) < 1 ? 2 : 0,
  });
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return `${(value * 100).toLocaleString("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  })}%`;
}

function correlationStyle(value: number | null) {
  if (value === null || Number.isNaN(value)) {
    return {};
  }
  const alpha = Math.min(0.82, Math.abs(value) * 0.72 + 0.12);
  const color = value >= 0 ? `rgba(34, 197, 94, ${alpha})` : `rgba(220, 38, 38, ${alpha})`;
  return { background: color };
}

function shortFactorLabel(name: string, definitions: FactorDefinition[]) {
  const definition = definitions.find((item) => item.name === name);
  return definition?.label.replace("60日", "60").replace("30日", "30").replace("20日", "20") ?? name;
}

export function FactorEvaluationPanel({
  definitions,
  isLoading,
  poolReport,
  report,
}: FactorEvaluationPanelProps) {
  if (isLoading) {
    return (
      <section className="section evaluationSection">
        <div className="sectionHeader">
          <div>
            <p className="eyebrow">FACTOR EVALUATION</p>
            <h2>评估报告加载中</h2>
          </div>
        </div>
        <div className="diagnosticsEmpty">正在计算 IC、分位数收益和相关性矩阵...</div>
      </section>
    );
  }

  if (!report) {
    return (
      <section className="section evaluationSection">
        <div className="sectionHeader">
          <div>
            <p className="eyebrow">FACTOR EVALUATION</p>
            <h2>因子评估报告</h2>
          </div>
        </div>
        <div className="diagnosticsEmpty">当前样本不足，暂不生成评估报告</div>
      </section>
    );
  }

  const primaryQuantile =
    report.quantile_returns["20"] ??
    Object.values(report.quantile_returns).sort((left, right) => right.horizon_days - left.horizon_days)[0];
  const decayEntries = Object.entries(report.ic.ic_by_horizon).sort(
    ([left], [right]) => Number(left) - Number(right)
  );
  const icPreview = report.ic.ic_series.slice(-24);
  const matrix = poolReport?.correlation_matrix ?? report.correlations;
  const verdictClass =
    report.overall_verdict === "可用"
      ? "ok"
      : report.overall_verdict === "不推荐单独使用"
        ? "error"
        : "stale";

  return (
    <section className="section evaluationSection">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">FACTOR EVALUATION</p>
          <h2>{shortFactorLabel(report.factor_name, definitions)} 评估摘要</h2>
        </div>
        <span className="sectionMeta">
          {report.period_start ?? "-"} / {report.period_end ?? "-"}
        </span>
      </div>

      <div className="evaluationGrid">
        <div className="evaluationCard verdictCard">
          <h3>
            <Activity size={15} />
            因子结论
          </h3>
          <span className={`statusBadge ${verdictClass}`}>{report.overall_verdict}</span>
          <dl>
            <dt>平均资产数</dt>
            <dd>{formatNumber(report.num_assets_avg, 1)}</dd>
            <dt>IC 样本</dt>
            <dd>{report.ic.num_periods}</dd>
            <dt>因子池</dt>
            <dd>{poolReport?.pool_health ?? "-"}</dd>
          </dl>
        </div>

        <div className="evaluationCard">
          <h3>
            <TrendingUp size={15} />
            Rank IC
          </h3>
          <div className="metricStrip">
            <span>MEAN<strong>{formatNumber(report.ic.rank_ic_mean)}</strong></span>
            <span>ICIR<strong>{formatNumber(report.ic.icir)}</strong></span>
            <span>WIN<strong>{formatPercent(report.ic.ic_pos_ratio)}</strong></span>
            <span>T-STAT<strong>{formatNumber(report.ic.ic_t_stat, 2)}</strong></span>
          </div>
          <div className="icSparkline" aria-label="Rank IC series">
            {icPreview.map((point) => (
              <span
                className={point.ic_value >= 0 ? "positiveBar" : "negativeBar"}
                key={`${point.date}-${point.ic_value}`}
                style={{
                  height: `${Math.max(3, Math.min(42, Math.abs(point.ic_value) * 120))}px`,
                }}
                title={`${point.date}: ${formatNumber(point.ic_value)}`}
              />
            ))}
          </div>
        </div>

        <div className="evaluationCard">
          <h3>
            <GitCompare size={15} />
            IC 衰减
          </h3>
          <div className="decayBars">
            {decayEntries.map(([horizon, value]) => (
              <span key={horizon}>
                <em>{horizon}D</em>
                <strong>{formatNumber(value)}</strong>
                <i
                  style={{
                    width: `${Math.max(4, Math.min(100, Math.abs(value ?? 0) * 320))}%`,
                  }}
                />
              </span>
            ))}
          </div>
        </div>

        <div className="evaluationCard">
          <h3>
            <Grid3X3 size={15} />
            分位数收益
          </h3>
          <dl>
            <dt>周期</dt>
            <dd>{primaryQuantile?.horizon_days ?? "-"}D</dd>
            <dt>Q1-Q5</dt>
            <dd>{formatPercent(primaryQuantile?.spread)}</dd>
            <dt>单调性</dt>
            <dd>{primaryQuantile?.is_monotonic ? "通过" : "待观察"}</dd>
          </dl>
          <div className="quantileBars">
            {Object.entries(primaryQuantile?.quantile_returns ?? {}).map(([label, value]) => (
              <span key={label}>
                <em>{label}</em>
                <strong>{formatPercent(value)}</strong>
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="evaluationMatrixGrid">
        <div className="evaluationCard">
          <h3>
            <Grid3X3 size={15} />
            因子相关性
          </h3>
          {matrix && matrix.factor_names.length > 0 ? (
            <div
              className="correlationMatrix"
              style={{ gridTemplateColumns: `92px repeat(${matrix.factor_names.length}, 1fr)` }}
            >
              <span />
              {matrix.factor_names.map((name) => (
                <b key={name}>{shortFactorLabel(name, definitions)}</b>
              ))}
              {matrix.factor_names.map((rowName, rowIndex) => (
                <Fragment key={rowName}>
                  <b key={`${rowName}-label`}>{shortFactorLabel(rowName, definitions)}</b>
                  {matrix.matrix[rowIndex]?.map((value, columnIndex) => (
                    <span
                      key={`${rowName}-${matrix.factor_names[columnIndex]}`}
                      style={correlationStyle(value)}
                    >
                      {formatNumber(value, 2)}
                    </span>
                  ))}
                </Fragment>
              ))}
            </div>
          ) : (
            <p>相关性样本不足。</p>
          )}
        </div>

        <div className="evaluationCard">
          <h3>
            <AlertTriangle size={15} />
            评估提示
          </h3>
          <div className="warningList">
            {(report.warnings.length ? report.warnings : ["暂未触发评估预警。"]).map((item) => (
              <p key={item}>{item}</p>
            ))}
            {poolReport?.recommendations.slice(0, 3).map((item) => <p key={item}>{item}</p>)}
          </div>
        </div>
      </div>
    </section>
  );
}
