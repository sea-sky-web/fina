import { Activity, AlertTriangle, CheckCircle2, Search } from "lucide-react";

import type { FactorDefinition, ResearchSignal, SignalComponent } from "../types/etf";
import { FactorHelpTooltip } from "./FactorHelpTooltip";

type SignalPanelProps = {
  selectedSignal: ResearchSignal | null;
  signals: ResearchSignal[];
  activeTheme: string;
  selectedSymbol: string | null;
  definitions: FactorDefinition[];
  onSelect: (symbol: string) => void;
};

function formatValue(component: SignalComponent) {
  if (component.value_format === "amount") {
    if (component.factor_value >= 100000000) {
      return `${(component.factor_value / 100000000).toLocaleString("zh-CN", {
        maximumFractionDigits: 2,
      })} 亿`;
    }
    if (component.factor_value >= 10000) {
      return `${(component.factor_value / 10000).toLocaleString("zh-CN", {
        maximumFractionDigits: 2,
      })} 万`;
    }
    return component.factor_value.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  }
  if (component.value_format === "ratio") {
    return component.factor_value.toLocaleString("zh-CN", { maximumFractionDigits: 3 });
  }
  return `${(component.factor_value * 100).toLocaleString("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  })}%`;
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return `${(value * 100).toLocaleString("zh-CN", { maximumFractionDigits: 0 })}%`;
}

function directionLabel(direction: SignalComponent["direction"]) {
  return direction === "lower_better" ? "低值更有利" : "高值更有利";
}

export function SignalPanel({
  selectedSignal,
  signals,
  activeTheme,
  selectedSymbol,
  definitions,
  onSelect,
}: SignalPanelProps) {
  const topSignals = signals.slice(0, 12);
  const definitionByName = new Map(definitions.map((definition) => [definition.name, definition]));

  return (
    <section className="section signalSection">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">RESEARCH SIGNAL</p>
          <h2>ETF 技术因子研究信号台</h2>
        </div>
        <span className="sectionMeta">
          {activeTheme} / {signals.length.toLocaleString("zh-CN")} signals
        </span>
      </div>
      <div className="signalGrid">
        <div className="signalDetail">
          {selectedSignal ? (
            <>
              <div className="signalScoreRow">
                <div>
                  <span className="signalSymbol">{selectedSignal.symbol}</span>
                  <h3>{selectedSignal.name}</h3>
                  <p>
                    {selectedSignal.theme} / {selectedSignal.date} / {selectedSignal.provider} /{" "}
                    {selectedSignal.market_regime?.label_zh ?? "中性"} / 暴露{" "}
                    {formatPercent(selectedSignal.target_exposure)}
                  </p>
                </div>
                <div className="signalScore">
                  <strong>{selectedSignal.research_score.toFixed(1)}</strong>
                  <span>{selectedSignal.priority}</span>
                </div>
              </div>

              <div className="componentGrid">
                {selectedSignal.components.map((component) => (
                  <div className="componentCell" key={component.factor_name}>
                    <div>
                      <strong>
                        {component.label}
                        <FactorHelpTooltip
                          compact
                          definition={definitionByName.get(component.factor_name)}
                        />
                      </strong>
                      <span>{directionLabel(component.direction)}</span>
                    </div>
                    <dl>
                      <dt>VALUE</dt>
                      <dd>{formatValue(component)}</dd>
                      <dt>PCTL</dt>
                      <dd>{formatPercent(component.percentile)}</dd>
                      <dt>WGT</dt>
                      <dd>{formatPercent(component.weight)}</dd>
                      <dt>PTS</dt>
                      <dd>{component.contribution.toFixed(1)}</dd>
                    </dl>
                  </div>
                ))}
              </div>

              <div className="signalNotesGrid">
                <div className="signalNotes">
                  <h4>
                    <CheckCircle2 size={14} />
                    观察理由
                  </h4>
                  {selectedSignal.explanation.positive_drivers.map((note) => (
                    <p key={note}>{note}</p>
                  ))}
                </div>
                <div className="signalNotes">
                  <h4>
                    <AlertTriangle size={14} />
                    风险提示
                  </h4>
                  {selectedSignal.explanation.risk_notes.map((note) => (
                    <p key={note}>{note}</p>
                  ))}
                </div>
                <div className="signalNotes">
                  <h4>
                    <Search size={14} />
                    待验证条件
                  </h4>
                  {selectedSignal.explanation.validation_notes.map((note) => (
                    <p key={note}>{note}</p>
                  ))}
                </div>
                <div className="signalNotes">
                  <h4>
                    <Activity size={14} />
                    数据说明
                  </h4>
                  {selectedSignal.explanation.data_notes.map((note) => (
                    <p key={note}>{note}</p>
                  ))}
                </div>
              </div>
            </>
          ) : (
            <div className="emptySignal">请选择 ETF 查看研究信号解释</div>
          )}
        </div>

        <div className="signalList">
          <table>
            <thead>
              <tr>
                <th>分数</th>
                <th>代码</th>
                <th>名称</th>
                <th>关注度</th>
              </tr>
            </thead>
            <tbody>
              {topSignals.map((signal) => (
                <tr
                  className={signal.symbol === selectedSymbol ? "selected" : ""}
                  key={`${signal.date}-${signal.symbol}`}
                  onClick={() => onSelect(signal.symbol)}
                >
                  <td className="signalScoreCell">{signal.research_score.toFixed(1)}</td>
                  <td>{signal.symbol}</td>
                  <td>{signal.name}</td>
                  <td>{signal.priority}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
