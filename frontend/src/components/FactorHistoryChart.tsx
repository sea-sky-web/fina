import type { FactorHistoryPoint } from "../types/etf";

type FactorHistoryChartProps = {
  history: FactorHistoryPoint[];
  symbol: string;
  factorLabel: string;
};

export function FactorHistoryChart({ history, symbol, factorLabel }: FactorHistoryChartProps) {
  if (history.length === 0) {
    return (
      <div className="emptyChart" style={{ height: 200 }}>
        暂无 {symbol} 的 {factorLabel} 历史数据
      </div>
    );
  }

  const width = 760;
  const height = 200;
  const marginLeft = 42;
  const marginRight = 16;
  const marginTop = 14;
  const marginBottom = 28;
  const plotWidth = width - marginLeft - marginRight;
  const plotHeight = height - marginTop - marginBottom;
  const maxRank = Math.max(...history.map((point) => point.rank), 1);
  const xAt = (index: number) =>
    marginLeft + (index / Math.max(history.length - 1, 1)) * plotWidth;
  const yAt = (rank: number) =>
    marginTop + ((rank - 1) / Math.max(maxRank - 1, 1)) * plotHeight;
  const points = history
    .map((point, index) => `${xAt(index).toFixed(1)},${yAt(point.rank).toFixed(1)}`)
    .join(" ");
  const rankTicks = [1, Math.max(1, Math.round(maxRank / 2)), maxRank];
  const dateTicks = [
    { index: 0, date: history[0].date },
    { index: Math.floor(history.length / 2), date: history[Math.floor(history.length / 2)].date },
    { index: history.length - 1, date: history[history.length - 1].date },
  ];

  return (
    <div className="factorHistoryChart">
      <svg aria-label={`${symbol} ${factorLabel} 排名历史`} role="img" viewBox={`0 0 ${width} ${height}`}>
        <rect height={height} width={width} x="0" y="0" />
        {rankTicks.map((rank) => (
          <g key={rank}>
            <line
              className="gridLine"
              x1={marginLeft}
              x2={width - marginRight}
              y1={yAt(rank)}
              y2={yAt(rank)}
            />
            <text className="axisText" x={marginLeft - 10} y={yAt(rank) + 4}>
              {rank}
            </text>
          </g>
        ))}
        {dateTicks.map((tick) => (
          <text className="xAxisText" key={`${tick.date}-${tick.index}`} x={xAt(tick.index)} y={height - 8}>
            {tick.date.slice(5)}
          </text>
        ))}
        <polyline className="factorRankLine" points={points} />
        <circle
          className="factorRankDot"
          cx={xAt(history.length - 1)}
          cy={yAt(history[history.length - 1].rank)}
          r="3"
        />
      </svg>
    </div>
  );
}
