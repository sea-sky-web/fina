import { BarChart3, History, LineChart, Play, ShieldAlert } from "lucide-react";
import type { BacktestEquityPoint, BacktestMetrics, BacktestResult } from "../types/etf";

type BacktestPanelProps = {
  result: BacktestResult | null;
  isLoading: boolean;
  topN: number;
  costBps: number;
  isStale: boolean;
  onTopNChange: (value: number) => void;
  onCostBpsChange: (value: number) => void;
  onRun: () => void;
  onSelect: (symbol: string) => void;
};

type Series = {
  key: string;
  label: string;
  color: string;
  points: BacktestEquityPoint[];
};

function formatPercent(value: number | null, digits = 2) {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return `${(value * 100).toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })}%`;
}

function formatNumber(value: number | null, digits = 2) {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return value.toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function metricItems(metrics: BacktestMetrics) {
  return [
    { label: "累计收益", value: formatPercent(metrics.cumulative_return) },
    { label: "年化收益", value: formatPercent(metrics.annualized_return) },
    { label: "年化波动", value: formatPercent(metrics.annualized_volatility) },
    { label: "最大回撤", value: formatPercent(metrics.max_drawdown) },
    { label: "Sharpe-like", value: formatNumber(metrics.sharpe_like) },
    { label: "日胜率", value: formatPercent(metrics.win_rate_daily) },
    { label: "平均换手", value: formatPercent(metrics.average_turnover) },
    { label: "调仓次数", value: metrics.rebalance_count.toLocaleString("zh-CN") },
  ];
}

function riskMetricItems(result: BacktestResult) {
  const summary = result.risk_summary;
  if (!summary) {
    return [];
  }
  return [
    { label: "目标暴露", value: formatPercent(summary.average_target_exposure) },
    { label: "实际暴露", value: formatPercent(summary.average_realized_exposure) },
    { label: "现金权重", value: formatPercent(summary.average_cash_weight) },
    { label: "防御调仓", value: summary.risk_off_rebalance_count.toLocaleString("zh-CN") },
    { label: "约束调仓", value: summary.constrained_rebalance_count.toLocaleString("zh-CN") },
  ];
}

function buildPath(points: BacktestEquityPoint[], width: number, height: number, min: number, max: number) {
  if (points.length === 0) {
    return "";
  }
  const span = Math.max(max - min, 0.0001);
  return points
    .map((point, index) => {
      const x = points.length === 1 ? 0 : (index / (points.length - 1)) * width;
      const y = height - ((point.equity - min) / span) * height;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function EquityCurveChart({ series }: { series: Series[] }) {
  const width = 820;
  const height = 280;
  const allPoints = series.flatMap((item) => item.points);
  if (allPoints.length === 0) {
    return <div className="backtestEmpty">当前样本不足，暂不生成净值曲线</div>;
  }
  const min = Math.min(...allPoints.map((point) => point.equity));
  const max = Math.max(...allPoints.map((point) => point.equity));
  const firstDate = allPoints[0]?.date ?? "-";
  const lastDate = allPoints[allPoints.length - 1]?.date ?? "-";

  return (
    <div className="backtestChartBox">
      <div className="backtestLegend">
        {series.map((item) => (
          <span key={item.key}>
            <i style={{ background: item.color }} />
            {item.label}
          </span>
        ))}
      </div>
      <svg className="backtestSvg" role="img" viewBox={`0 0 ${width} ${height}`}>
        <rect height={height} width={width} />
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = ratio * height;
          const value = max - ratio * (max - min);
          return (
            <g key={ratio}>
              <line className="gridLine" x1="0" x2={width} y1={y} y2={y} />
              <text className="backtestAxisText" x={width - 4} y={Math.max(12, y - 4)}>
                {value.toFixed(2)}
              </text>
            </g>
          );
        })}
        {series.map((item) => (
          <path
            className="backtestLine"
            d={buildPath(item.points, width, height, min, max)}
            key={item.key}
            style={{ stroke: item.color }}
          />
        ))}
      </svg>
      <div className="backtestDateRange">
        <span>{firstDate}</span>
        <span>{lastDate}</span>
      </div>
    </div>
  );
}

export function BacktestPanel({
  result,
  isLoading,
  topN,
  costBps,
  isStale,
  onTopNChange,
  onCostBpsChange,
  onRun,
  onSelect,
}: BacktestPanelProps) {
  const series: Series[] = result
    ? [
        {
          key: "strategy",
          label: `研究信号Top${result.config.top_n}`,
          color: "#f5a400",
          points: result.equity_curve,
        },
        ...result.benchmarks.map((benchmark, index) => ({
          key: benchmark.key,
          label: benchmark.label,
          color: index === 0 ? "#60a5fa" : "#a78bfa",
          points: benchmark.equity_curve,
        })),
      ]
    : [];
  const latestSnapshot = result?.holdings[result.holdings.length - 1] ?? null;

  return (
    <section className="section backtestSection">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">STRATEGY VALIDATION</p>
          <h2>综合研究信号历史策略验证</h2>
        </div>
        <span className="sectionMeta">monthly / dynamic risk / research only</span>
      </div>

      <div className="backtestControls">
        <label>
          TOP N
          <select onChange={(event) => onTopNChange(Number(event.target.value))} value={topN}>
            {[5, 10, 20].map((value) => (
              <option key={value} value={value}>
                Top {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          单边成本
          <select onChange={(event) => onCostBpsChange(Number(event.target.value))} value={costBps}>
            {[0, 5, 10, 20].map((value) => (
              <option key={value} value={value}>
                {value} bp
              </option>
            ))}
          </select>
        </label>
        <button
          className="controlButton"
          disabled={isLoading}
          onClick={onRun}
          title="按当前参数运行历史策略验证"
          type="button"
        >
          <Play size={13} />
          {isLoading ? "计算中..." : result ? "重新运行回测" : "运行回测"}
        </button>
        <div className="backtestRule">
          {isStale
            ? "参数已修改，点击运行回测刷新结果。"
            : "月末读取信号，下一交易日生效，按市场状态与风险约束配置权重。"}
        </div>
      </div>

      {isLoading ? (
        <div className="backtestEmpty">正在计算历史策略样本...</div>
      ) : result ? (
        <>
          <div className="backtestMainGrid">
            <div>
              <EquityCurveChart series={series} />
            </div>
            <div className="backtestMetricPanel">
              <h3>
                <BarChart3 size={15} />
                组合指标
              </h3>
              <div className="metricGrid">
                {metricItems(result.metrics).map((item) => (
                  <span key={item.label}>
                    {item.label}
                    <strong>{item.value}</strong>
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="benchmarkGrid">
            {result.risk_summary ? (
              <div className="benchmarkCard riskSummaryCard">
                <h3>
                  <ShieldAlert size={15} />
                  风险控制摘要
                </h3>
                <div className="metricGrid compact">
                  {riskMetricItems(result).map((item) => (
                    <span key={item.label}>
                      {item.label}
                      <strong>{item.value}</strong>
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
            {result.benchmarks.map((benchmark) => (
              <div className="benchmarkCard" key={benchmark.key}>
                <h3>
                  <LineChart size={15} />
                  {benchmark.label}
                </h3>
                <div className="metricGrid compact">
                  {metricItems(benchmark.metrics).slice(0, 4).map((item) => (
                    <span key={item.label}>
                      {item.label}
                      <strong>{item.value}</strong>
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="backtestDetailGrid">
            <div className="holdingPanel">
              <h3>
                <History size={15} />
                最新调仓快照
              </h3>
              {latestSnapshot ? (
                <>
                  <div className="snapshotMeta">
                    <span>信号日 {latestSnapshot.rebalance_date}</span>
                    <span>生效日 {latestSnapshot.effective_date ?? "-"}</span>
                    <span>状态 {latestSnapshot.regime?.label_zh ?? "-"}</span>
                    <span>暴露 {formatPercent(latestSnapshot.realized_exposure)}</span>
                    <span>现金 {formatPercent(latestSnapshot.cash_weight)}</span>
                    <span>换手 {formatPercent(latestSnapshot.turnover)}</span>
                    <span>成本 {formatPercent(latestSnapshot.cost)}</span>
                  </div>
                  <div className="holdingTableWrap">
                    <table>
                      <thead>
                        <tr>
                          <th>代码</th>
                          <th>名称</th>
                          <th>主题</th>
                          <th>分数</th>
                          <th>权重</th>
                        </tr>
                      </thead>
                      <tbody>
                        {latestSnapshot.holdings.map((holding) => (
                          <tr key={holding.symbol} onClick={() => onSelect(holding.symbol)}>
                            <td>{holding.symbol}</td>
                            <td>{holding.name}</td>
                            <td>{holding.theme}</td>
                            <td className="signalScoreCell">{holding.research_score.toFixed(1)}</td>
                            <td>{formatPercent(holding.weight)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <div className="backtestEmpty small">暂无调仓样本</div>
              )}
            </div>
            <div className="riskNotePanel">
              <h3>
                <ShieldAlert size={15} />
                规则与风险解释
              </h3>
              {result.data_notes.map((note) => (
                <p className={note.severity} key={note.message}>
                  {note.message}
                </p>
              ))}
              {result.risk_summary?.data_notes.map((note) => (
                <p key={note}>{note}</p>
              ))}
              {latestSnapshot?.risk_notes.map((note) => (
                <p key={note}>{note}</p>
              ))}
              <p>策略验证用于回答“如果按固定规则执行，历史样本发生了什么”，不是实盘执行建议。</p>
            </div>
          </div>
        </>
      ) : (
        <div className="backtestEmpty">点击运行回测生成策略验证结果</div>
      )}
    </section>
  );
}
