import { Info } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { FactorDefinition } from "../types/etf";

type FactorHelpTooltipProps = {
  definition?: FactorDefinition | null;
  label?: string;
  compact?: boolean;
};

const CATEGORY_LABELS: Record<string, string> = {
  return: "收益",
  risk: "风险",
  liquidity: "流动性",
  trend: "趋势",
};

const FORMAT_LABELS: Record<string, string> = {
  percent: "百分比",
  amount: "金额",
  ratio: "比率",
};

function directionLabel(direction?: FactorDefinition["direction"]) {
  return direction === "lower_better" ? "低值更有利" : "高值更有利";
}

export function FactorHelpTooltip({ definition, label = "因子说明", compact = false }: FactorHelpTooltipProps) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  if (!definition) {
    return null;
  }

  return (
    <span
      className={`factorHelp ${compact ? "compact" : ""}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      ref={wrapperRef}
    >
      <button
        aria-label={`${definition.label} 因子说明`}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((value) => !value);
        }}
        type="button"
      >
        <Info size={13} />
        {compact ? null : <span>{label}</span>}
      </button>
      {open ? (
        <span className="factorHelpBubble">
          <strong>{definition.label}</strong>
          <dl>
            <dt>计算方式</dt>
            <dd>{definition.description}</dd>
            <dt>含义</dt>
            <dd>{definition.interpretation}</dd>
            <dt>方向</dt>
            <dd>{directionLabel(definition.direction)}</dd>
            <dt>类别</dt>
            <dd>{CATEGORY_LABELS[definition.category] ?? definition.category}</dd>
            <dt>展示格式</dt>
            <dd>{FORMAT_LABELS[definition.format] ?? definition.format}</dd>
            <dt>局限</dt>
            <dd>{definition.limitation}</dd>
          </dl>
        </span>
      ) : null}
    </span>
  );
}
