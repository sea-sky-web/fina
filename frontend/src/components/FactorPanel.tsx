import type { FactorDefinition, FactorScore } from "../types/etf";
import { FactorHelpTooltip } from "./FactorHelpTooltip";

type FactorPanelProps = {
  scores: FactorScore[];
  definitions: FactorDefinition[];
  activeFactor: string;
  activeTheme: string;
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
  onFactorChange: (name: string) => void;
};

function formatPercent(value: number, fractionDigits = 2) {
  return `${(value * 100).toLocaleString("zh-CN", { maximumFractionDigits: fractionDigits })}%`;
}

function formatAmount(value: number) {
  if (value >= 100000000) {
    return `${(value / 100000000).toLocaleString("zh-CN", { maximumFractionDigits: 2 })} 亿`;
  }
  if (value >= 10000) {
    return `${(value / 10000).toLocaleString("zh-CN", { maximumFractionDigits: 2 })} 万`;
  }
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function formatFactor(value: number, factorName: string) {
  if (factorName === "turnover_20d") {
    return formatAmount(value);
  }
  return `${(value * 100).toLocaleString("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  })}%`;
}

function directionLabel(direction?: FactorDefinition["direction"]) {
  return direction === "lower_better" ? "低值更有利" : "高值更有利";
}

export function FactorPanel({
  scores,
  definitions,
  activeFactor,
  activeTheme,
  selectedSymbol,
  onSelect,
  onFactorChange,
}: FactorPanelProps) {
  const latestDate = scores[0]?.date ?? "-";
  const currentDef = definitions.find((d) => d.name === activeFactor);
  const definitionByName = new Map(definitions.map((definition) => [definition.name, definition]));

  return (
    <section className="section factorSection">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">FACTOR LAB</p>
          <h2>{currentDef?.label ?? activeFactor}</h2>
        </div>
        <span className="sectionMeta">
          {activeTheme} / {scores.length.toLocaleString("zh-CN")} scores / {latestDate}
        </span>
      </div>
      <div className="factorTabs">
        {definitions.map((def) => (
          <button
            className={`factorTab ${def.name === activeFactor ? "active" : ""}`}
            key={def.name}
            onClick={() => onFactorChange(def.name)}
            type="button"
          >
            {def.label}
            <FactorHelpTooltip compact definition={def} />
          </button>
        ))}
      </div>
      <div className="factorDefinition">
        <span>
          {currentDef?.description ?? activeFactor}
          <FactorHelpTooltip compact definition={currentDef} />
        </span>
        <strong>历史排序，仅用于研究展示</strong>
      </div>
      <div className="factorWrap">
        <table>
          <thead>
            <tr>
              <th>排名</th>
              <th>代码</th>
              <th>名称</th>
              <th>主题</th>
              <th>
                因子值
                <FactorHelpTooltip compact definition={currentDef} />
              </th>
              <th>
                分位数
                <FactorHelpTooltip compact definition={currentDef} />
              </th>
              <th>
                方向
                <FactorHelpTooltip compact definition={currentDef} />
              </th>
              <th>解释</th>
            </tr>
          </thead>
          <tbody>
            {scores.map((score) => {
              const definition = definitionByName.get(score.factor_name);
              return (
                <tr
                  className={score.symbol === selectedSymbol ? "selected" : ""}
                  key={`${score.factor_name}-${score.date}-${score.symbol}`}
                  onClick={() => onSelect(score.symbol)}
                >
                  <td>{score.rank}</td>
                  <td>{score.symbol}</td>
                  <td>{score.name}</td>
                  <td>{score.theme}</td>
                  <td className={score.factor_value >= 0 ? "positive" : "negative"}>
                    {formatFactor(score.factor_value, activeFactor)}
                  </td>
                  <td>{formatPercent(score.percentile)}</td>
                  <td>{directionLabel(definition?.direction)}</td>
                  <td className="factorExplainCell">{definition?.interpretation ?? "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
