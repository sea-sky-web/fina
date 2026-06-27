import { BarChart3, LineChart, Rows3, SplitSquareHorizontal } from "lucide-react";

import type { FactorDiagnostics, FactorScore } from "../types/etf";
import { FactorHelpTooltip } from "./FactorHelpTooltip";

type FactorDiagnosticsPanelProps = {
  diagnostics: FactorDiagnostics | null;
  isLoading: boolean;
  onSelect: (symbol: string) => void;
  selectedSymbol: string | null;
};

function formatNumber(value: number | null, digits = 3) {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return value.toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: Math.abs(value) < 1 ? 2 : 0,
  });
}

function formatPercent(value: number | null) {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return `${(value * 100).toLocaleString("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  })}%`;
}

function formatFactorValue(score: FactorScore, valueFormat?: string) {
  if (valueFormat === "amount") {
    if (score.factor_value >= 100000000) {
      return `${(score.factor_value / 100000000).toLocaleString("zh-CN", {
        maximumFractionDigits: 2,
      })} 亿`;
    }
    if (score.factor_value >= 10000) {
      return `${(score.factor_value / 10000).toLocaleString("zh-CN", {
        maximumFractionDigits: 2,
      })} 万`;
    }
    return score.factor_value.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  }
  if (valueFormat === "ratio") {
    return formatNumber(score.factor_value);
  }
  return formatPercent(score.factor_value);
}

function ScoreRows({
  rows,
  valueFormat,
  onSelect,
  selectedSymbol,
}: {
  rows: FactorScore[];
  valueFormat?: string;
  onSelect: (symbol: string) => void;
  selectedSymbol: string | null;
}) {
  return (
    <table>
      <thead>
        <tr>
          <th>排名</th>
          <th>代码</th>
          <th>名称</th>
          <th>值</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            className={row.symbol === selectedSymbol ? "selected" : ""}
            key={`${row.factor_name}-${row.date}-${row.symbol}`}
            onClick={() => onSelect(row.symbol)}
          >
            <td>{row.rank}</td>
            <td>{row.symbol}</td>
            <td>{row.name}</td>
            <td>{formatFactorValue(row, valueFormat)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function FactorDiagnosticsPanel({
  diagnostics,
  isLoading,
  onSelect,
  selectedSymbol,
}: FactorDiagnosticsPanelProps) {
  if (isLoading) {
    return (
      <section className="section factorDiagnosticsSection">
        <div className="sectionHeader">
          <div>
            <p className="eyebrow">FACTOR DIAGNOSTICS</p>
            <h2>历史诊断加载中</h2>
          </div>
        </div>
        <div className="diagnosticsEmpty">正在读取因子诊断数据...</div>
      </section>
    );
  }

  if (!diagnostics) {
    return (
      <section className="section factorDiagnosticsSection">
        <div className="sectionHeader">
          <div>
            <p className="eyebrow">FACTOR DIAGNOSTICS</p>
            <h2>因子历史诊断</h2>
          </div>
        </div>
        <div className="diagnosticsEmpty">当前样本不足，暂不解读有效性</div>
      </section>
    );
  }

  const { definition, distribution, forward_return: forwardReturn, stability } = diagnostics;

  return (
    <section className="section factorDiagnosticsSection">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">FACTOR DIAGNOSTICS</p>
          <h2>{definition.label} 历史诊断</h2>
        </div>
        <span className="sectionMeta">
          {diagnostics.date ?? "-"} / horizon {forwardReturn.horizon}
        </span>
      </div>

      <div className="diagnosticsGrid">
        <div className="diagnosticCard definitionCard">
          <h3>
            <BarChart3 size={15} />
            因子定义
            <FactorHelpTooltip compact definition={definition} />
          </h3>
          <p>{definition.interpretation}</p>
          <dl>
            <dt>计算方式</dt>
            <dd>{definition.description}</dd>
            <dt>方向</dt>
            <dd>{definition.direction === "lower_better" ? "低值更有利" : "高值更有利"}</dd>
            <dt>局限</dt>
            <dd>{definition.limitation}</dd>
          </dl>
        </div>

        <div className="diagnosticCard">
          <h3>
            <Rows3 size={15} />
            当前分布
          </h3>
          <div className="distributionGrid">
            <span>COUNT<strong>{distribution.count}</strong></span>
            <span>MISS<strong>{distribution.missing_count}</strong></span>
            <span>MIN<strong>{formatNumber(distribution.min)}</strong></span>
            <span>P25<strong>{formatNumber(distribution.p25)}</strong></span>
            <span>MED<strong>{formatNumber(distribution.median)}</strong></span>
            <span>P75<strong>{formatNumber(distribution.p75)}</strong></span>
            <span>MAX<strong>{formatNumber(distribution.max)}</strong></span>
            <span>MEAN<strong>{formatNumber(distribution.mean)}</strong></span>
          </div>
        </div>

        <div className="diagnosticCard">
          <h3>
            <LineChart size={15} />
            未来收益样本
          </h3>
          <dl>
            <dt>样本日期数</dt>
            <dd>{forwardReturn.sample_count}</dd>
            <dt>Top 20%</dt>
            <dd>{formatPercent(forwardReturn.top_mean)}</dd>
            <dt>Bottom 20%</dt>
            <dd>{formatPercent(forwardReturn.bottom_mean)}</dd>
            <dt>差值</dt>
            <dd>{formatPercent(forwardReturn.spread)}</dd>
          </dl>
          {forwardReturn.data_notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>

        <div className="diagnosticCard">
          <h3>
            <SplitSquareHorizontal size={15} />
            排名稳定性
          </h3>
          <dl>
            <dt>观察日期</dt>
            <dd>{stability.lookback_dates}</dd>
            <dt>平均排名变化</dt>
            <dd>{formatNumber(stability.average_rank_change, 2)}</dd>
            <dt>稳定性</dt>
            <dd>{stability.label}</dd>
          </dl>
          {stability.data_notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      </div>

      <div className="diagnosticsCompareGrid">
        <div>
          <h3>Top 样本</h3>
          <ScoreRows
            onSelect={onSelect}
            rows={diagnostics.top}
            selectedSymbol={selectedSymbol}
            valueFormat={definition.format}
          />
        </div>
        <div>
          <h3>Bottom 样本</h3>
          <ScoreRows
            onSelect={onSelect}
            rows={diagnostics.bottom}
            selectedSymbol={selectedSymbol}
            valueFormat={definition.format}
          />
        </div>
      </div>
    </section>
  );
}
