import { Maximize2, MoveHorizontal, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type MouseEvent, type WheelEvent } from "react";

import type { EtfDailyBar, FactorDefinition, FactorHistoryPoint } from "../types/etf";
import { FactorHelpTooltip } from "./FactorHelpTooltip";

type PriceChartProps = {
  symbol: string | null;
  bars: EtfDailyBar[];
  factorHistory: FactorHistoryPoint[];
  factorLabel: string;
  activeFactor: string;
  factorDefinition?: FactorDefinition;
};

type ChartBar = EtfDailyBar & {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type RangeKey = "1M" | "3M" | "6M" | "1Y" | "ALL" | "CUSTOM";
type ViewWindow = { start: number; end: number };
type DragState = { clientX: number; start: number; end: number };

const RANGES: Array<{ key: RangeKey; label: string; days: number | null }> = [
  { key: "1M", label: "1M", days: 30 },
  { key: "3M", label: "3M", days: 90 },
  { key: "6M", label: "6M", days: 180 },
  { key: "1Y", label: "1Y", days: 365 },
  { key: "ALL", label: "ALL", days: null }
];

const CHART = {
  width: 760,
  height: 760,
  marginLeft: 58,
  marginRight: 18,
  marginTop: 18,
  priceHeight: 390,
  gap: 18,
  volumeHeight: 95,
  factorHeight: 115,
  marginBottom: 42
};

const MIN_VISIBLE_BARS = 12;

function isCompleteBar(bar: EtfDailyBar): bar is ChartBar {
  return (
    bar.open !== null &&
    bar.high !== null &&
    bar.low !== null &&
    bar.close !== null &&
    bar.volume !== null
  );
}

function formatNumber(value: number, digits = 3) {
  return value.toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: value >= 100 ? 2 : 3
  });
}

function formatVolume(value: number) {
  if (value >= 100000000) {
    return `${(value / 100000000).toFixed(2)}亿`;
  }
  if (value >= 10000) {
    return `${(value / 10000).toFixed(2)}万`;
  }
  return value.toLocaleString("zh-CN");
}

function formatFactor(value: number, factorName: string) {
  if (factorName === "turnover_20d") {
    if (value >= 100000000) {
      return `${(value / 100000000).toFixed(2)}亿`;
    }
    if (value >= 10000) {
      return `${(value / 10000).toFixed(2)}万`;
    }
    return value.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  }
  return `${(value * 100).toLocaleString("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2
  })}%`;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function clampWindow(window: ViewWindow, sourceLength: number): ViewWindow | null {
  if (sourceLength <= 0 || window.start <= 0 && window.end >= sourceLength - 1) {
    return null;
  }
  const length = Math.max(window.end - window.start + 1, MIN_VISIBLE_BARS);
  const safeLength = Math.min(length, sourceLength);
  const start = clamp(window.start, 0, Math.max(sourceLength - safeLength, 0));
  return { start, end: start + safeLength - 1 };
}

export function PriceChart({
  symbol,
  bars,
  factorHistory,
  factorLabel,
  activeFactor,
  factorDefinition,
}: PriceChartProps) {
  const [range, setRange] = useState<RangeKey>("1Y");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [hover, setHover] = useState<{ index: number; x: number; y: number } | null>(null);
  const [viewWindow, setViewWindow] = useState<ViewWindow | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const dragRef = useRef<DragState | null>(null);

  const cleanBars = useMemo(
    () =>
      bars
        .filter(isCompleteBar)
        .slice()
        .sort((a, b) => a.date.localeCompare(b.date)),
    [bars]
  );

  const filteredBars = useMemo(() => {
    if (cleanBars.length === 0) {
      return [];
    }

    if (range === "CUSTOM") {
      return cleanBars.filter((bar) => {
        const afterStart = startDate ? bar.date >= startDate : true;
        const beforeEnd = endDate ? bar.date <= endDate : true;
        return afterStart && beforeEnd;
      });
    }

    const selectedRange = RANGES.find((item) => item.key === range);
    if (!selectedRange?.days) {
      return cleanBars;
    }

    const lastDate = new Date(cleanBars[cleanBars.length - 1].date);
    const start = new Date(lastDate);
    start.setDate(lastDate.getDate() - selectedRange.days);
    const startKey = start.toISOString().slice(0, 10);
    return cleanBars.filter((bar) => bar.date >= startKey);
  }, [cleanBars, endDate, range, startDate]);

  const sourceBars = filteredBars.length > 0 ? filteredBars : cleanBars;
  const effectiveWindow = viewWindow ? clampWindow(viewWindow, sourceBars.length) : null;
  const windowStart = effectiveWindow?.start ?? 0;
  const windowEnd = effectiveWindow?.end ?? Math.max(sourceBars.length - 1, 0);
  const chartData = sourceBars.slice(windowStart, windowEnd + 1);
  const activeBar = hover ? chartData[hover.index] : null;
  const factorByDate = useMemo(
    () => new Map(factorHistory.map((point) => [point.date, point])),
    [factorHistory]
  );
  const activeFactorPoint = activeBar ? factorByDate.get(activeBar.date) : undefined;
  const plotWidth = CHART.width - CHART.marginLeft - CHART.marginRight;
  const priceTop = CHART.marginTop;
  const priceBottom = CHART.marginTop + CHART.priceHeight;
  const volumeTop = priceBottom + CHART.gap;
  const volumeBottom = volumeTop + CHART.volumeHeight;
  const factorTop = volumeBottom + CHART.gap;
  const factorBottom = factorTop + CHART.factorHeight;
  const candleStep = chartData.length > 1 ? plotWidth / (chartData.length - 1) : plotWidth;
  const candleWidth = clamp(candleStep * 0.58, 2, 12);

  const minLow = chartData.length ? Math.min(...chartData.map((bar) => bar.low)) : 0;
  const maxHigh = chartData.length ? Math.max(...chartData.map((bar) => bar.high)) : 1;
  const pricePadding = Math.max((maxHigh - minLow) * 0.08, 0.001);
  const priceMin = minLow - pricePadding;
  const priceMax = maxHigh + pricePadding;
  const maxVolume = chartData.length ? Math.max(...chartData.map((bar) => bar.volume)) : 1;
  const visibleFactorPoints = chartData
    .map((bar, index) => ({ index, point: factorByDate.get(bar.date) }))
    .filter((item): item is { index: number; point: FactorHistoryPoint } => item.point !== undefined);
  const factorValues = visibleFactorPoints.map((item) => item.point.factor_value);
  const factorMinRaw = factorValues.length ? Math.min(...factorValues) : 0;
  const factorMaxRaw = factorValues.length ? Math.max(...factorValues) : 1;
  const factorPadding = Math.max((factorMaxRaw - factorMinRaw) * 0.1, 0.0001);
  const factorMin = factorMinRaw - factorPadding;
  const factorMax = factorMaxRaw + factorPadding;
  const factorLinePoints = visibleFactorPoints
    .map((item) => `${xAt(item.index).toFixed(1)},${factorY(item.point.factor_value).toFixed(1)}`)
    .join(" ");

  useEffect(() => {
    setViewWindow(null);
    setHover(null);
    setDrag(null);
    dragRef.current = null;
  }, [symbol]);

  function xAt(index: number) {
    return CHART.marginLeft + index * candleStep;
  }

  function priceY(value: number) {
    return priceBottom - ((value - priceMin) / (priceMax - priceMin)) * CHART.priceHeight;
  }

  function volumeY(value: number) {
    return volumeBottom - (value / maxVolume) * CHART.volumeHeight;
  }

  function factorY(value: number) {
    return factorBottom - ((value - factorMin) / (factorMax - factorMin)) * CHART.factorHeight;
  }

  function indexInfoFromEvent(event: MouseEvent<SVGSVGElement> | WheelEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / rect.width) * CHART.width;
    const ratio = clamp((svgX - CHART.marginLeft) / plotWidth, 0, 1);
    const index = clamp(Math.round(ratio * Math.max(chartData.length - 1, 0)), 0, chartData.length - 1);
    return { index, ratio, rect };
  }

  function handleMouseMove(event: MouseEvent<SVGSVGElement>) {
    if (chartData.length === 0) {
      return;
    }
    const { index, rect } = indexInfoFromEvent(event);
    setHover({ index, x: event.clientX - rect.left, y: event.clientY - rect.top });

    const activeDrag = dragRef.current;
    if (!activeDrag || sourceBars.length <= chartData.length) {
      return;
    }
    const pixelStep = (candleStep / CHART.width) * rect.width;
    const movedSteps = Math.round((event.clientX - activeDrag.clientX) / Math.max(pixelStep, 1));
    const windowLength = activeDrag.end - activeDrag.start + 1;
    const nextStart = clamp(activeDrag.start - movedSteps, 0, Math.max(sourceBars.length - windowLength, 0));
    setViewWindow({ start: nextStart, end: nextStart + windowLength - 1 });
  }

  function applyZoom(multiplier: number, anchorRatio = 0.5) {
    if (sourceBars.length <= MIN_VISIBLE_BARS) {
      return;
    }
    const currentLength = windowEnd - windowStart + 1;
    const nextLength = clamp(
      Math.round(currentLength * multiplier),
      Math.min(MIN_VISIBLE_BARS, sourceBars.length),
      sourceBars.length
    );
    if (nextLength >= sourceBars.length) {
      setViewWindow(null);
      return;
    }
    const anchor = windowStart + anchorRatio * Math.max(currentLength - 1, 1);
    const nextStart = clamp(
      Math.round(anchor - anchorRatio * Math.max(nextLength - 1, 1)),
      0,
      sourceBars.length - nextLength
    );
    setViewWindow({ start: nextStart, end: nextStart + nextLength - 1 });
  }

  function handleWheel(event: WheelEvent<SVGSVGElement>) {
    if (chartData.length === 0) {
      return;
    }
    event.preventDefault();
    const { ratio } = indexInfoFromEvent(event);
    applyZoom(event.deltaY < 0 ? 0.72 : 1.35, ratio);
  }

  function handleMouseDown(event: MouseEvent<SVGSVGElement>) {
    if (sourceBars.length <= chartData.length) {
      return;
    }
    const nextDrag = { clientX: event.clientX, start: windowStart, end: windowEnd };
    dragRef.current = nextDrag;
    setDrag(nextDrag);
  }

  function stopDrag() {
    dragRef.current = null;
    setDrag(null);
  }

  function resetView() {
    setViewWindow(null);
    setHover(null);
    stopDrag();
  }

  function handleRangeClick(nextRange: RangeKey) {
    setRange(nextRange);
    resetView();
    if (nextRange !== "CUSTOM") {
      setStartDate("");
      setEndDate("");
    }
  }

  const yTicks = Array.from({ length: 5 }, (_, index) => {
    const value = priceMin + ((priceMax - priceMin) / 4) * index;
    return { value, y: priceY(value) };
  });
  const factorTicks = Array.from({ length: 3 }, (_, index) => {
    const value = factorMin + ((factorMax - factorMin) / 2) * index;
    return { value, y: factorY(value) };
  });
  const xTickCount = Math.min(5, chartData.length);
  const xTicks = Array.from({ length: xTickCount }, (_, index) => {
    const sourceIndex =
      xTickCount === 1 ? 0 : Math.round((index / (xTickCount - 1)) * (chartData.length - 1));
    return { date: chartData[sourceIndex].date, x: xAt(sourceIndex) };
  });
  const viewStartDate = chartData[0]?.date ?? "-";
  const viewEndDate = chartData[chartData.length - 1]?.date ?? "-";
  const isZoomed = chartData.length < sourceBars.length;

  return (
    <section className="section chartSection">
      <div className="sectionHeader chartHeader">
        <div>
          <p className="eyebrow">OHLC / VOLUME / FACTOR</p>
          <h2>{symbol ?? "请选择 ETF"}</h2>
        </div>
        <div className="chartControls">
          <div className="rangeButtons" aria-label="日期范围">
            {RANGES.map((item) => (
              <button
                className={range === item.key ? "active" : ""}
                key={item.key}
                onClick={() => handleRangeClick(item.key)}
                type="button"
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="dateInputs">
            <input
              aria-label="开始日期"
              max={endDate || undefined}
              onChange={(event) => {
                setStartDate(event.target.value);
                setRange("CUSTOM");
                resetView();
              }}
              type="date"
              value={startDate}
            />
            <input
              aria-label="结束日期"
              min={startDate || undefined}
              onChange={(event) => {
                setEndDate(event.target.value);
                setRange("CUSTOM");
                resetView();
              }}
              type="date"
              value={endDate}
            />
          </div>
          <div className="chartToolButtons" aria-label="图表缩放和平移">
            <button aria-label="放大图表" onClick={() => applyZoom(0.72)} title="放大" type="button">
              <ZoomIn size={15} />
            </button>
            <button aria-label="缩小图表" onClick={() => applyZoom(1.35)} title="缩小" type="button">
              <ZoomOut size={15} />
            </button>
            <button aria-label="适配全视图" onClick={resetView} title="适配全视图" type="button">
              <Maximize2 size={15} />
            </button>
            <span className={isZoomed ? "active" : ""} title="拖拽图表可横向平移">
              <MoveHorizontal size={15} />
            </span>
          </div>
        </div>
      </div>
      <div className="chartViewMeta">
        <span>
          VIEW {viewStartDate} - {viewEndDate}
        </span>
        <strong>
          {chartData.length.toLocaleString("zh-CN")} / {sourceBars.length.toLocaleString("zh-CN")} bars
        </strong>
        <span className="chartFactorHelp">
          FACTOR {factorLabel}
          <FactorHelpTooltip compact definition={factorDefinition} />
        </span>
        <em>滚轮缩放 / 拖拽平移 / 悬浮查看 OHLC + 因子</em>
      </div>
      <div className="chartBox">
        {chartData.length === 0 ? (
          <div className="emptyChart">暂无可用 OHLC 数据</div>
        ) : (
          <div className="ohlcStage">
            <svg
              className={`ohlcSvg ${drag ? "dragging" : ""}`}
              onMouseDown={handleMouseDown}
              onMouseLeave={() => {
                setHover(null);
                stopDrag();
              }}
              onMouseMove={handleMouseMove}
              onMouseUp={stopDrag}
              onWheel={handleWheel}
              role="img"
              viewBox={`0 0 ${CHART.width} ${CHART.height}`}
            >
              <rect height={CHART.height} width={CHART.width} x="0" y="0" />

              {yTicks.map((tick) => (
                <g key={tick.value}>
                  <line
                    className="gridLine"
                    x1={CHART.marginLeft}
                    x2={CHART.width - CHART.marginRight}
                    y1={tick.y}
                    y2={tick.y}
                  />
                  <text className="axisText" x={CHART.marginLeft - 10} y={tick.y + 4}>
                    {formatNumber(tick.value, 3)}
                  </text>
                </g>
              ))}

              {xTicks.map((tick) => (
                <g key={tick.date}>
                  <line
                    className="gridLine vertical"
                    x1={tick.x}
                    x2={tick.x}
                    y1={priceTop}
                    y2={factorBottom}
                  />
                  <text className="xAxisText" x={tick.x} y={factorBottom + 28}>
                    {tick.date.slice(5)}
                  </text>
                </g>
              ))}

              <line
                className="axisLine"
                x1={CHART.marginLeft}
                x2={CHART.width - CHART.marginRight}
                y1={priceBottom}
                y2={priceBottom}
              />
              <line
                className="axisLine"
                x1={CHART.marginLeft}
                x2={CHART.width - CHART.marginRight}
                y1={volumeBottom}
                y2={volumeBottom}
              />
              <line
                className="axisLine"
                x1={CHART.marginLeft}
                x2={CHART.width - CHART.marginRight}
                y1={factorBottom}
                y2={factorBottom}
              />

              <text className="panelLabel" x={CHART.marginLeft} y={volumeTop + 12}>
                VOLUME
              </text>
              <text className="panelLabel" x={CHART.marginLeft} y={factorTop + 12}>
                {factorLabel}
              </text>

              {factorTicks.map((tick) => (
                <g key={tick.value}>
                  <line
                    className="gridLine"
                    x1={CHART.marginLeft}
                    x2={CHART.width - CHART.marginRight}
                    y1={tick.y}
                    y2={tick.y}
                  />
                  <text className="axisText" x={CHART.marginLeft - 10} y={tick.y + 4}>
                    {formatFactor(tick.value, activeFactor)}
                  </text>
                </g>
              ))}

              {chartData.map((bar, index) => {
                const x = xAt(index);
                const openY = priceY(bar.open);
                const closeY = priceY(bar.close);
                const highY = priceY(bar.high);
                const lowY = priceY(bar.low);
                const isUp = bar.close >= bar.open;
                const colorClass = isUp ? "upCandle" : "downCandle";
                const bodyY = Math.min(openY, closeY);
                const bodyHeight = Math.max(Math.abs(closeY - openY), 1.5);
                const volumeHeight = volumeBottom - volumeY(bar.volume);
                return (
                  <g className={colorClass} key={`${bar.symbol}-${bar.date}`}>
                    <line className="wick" x1={x} x2={x} y1={highY} y2={lowY} />
                    <rect
                      className="candleBody"
                      height={bodyHeight}
                      width={candleWidth}
                      x={x - candleWidth / 2}
                      y={bodyY}
                    />
                    <rect
                      className="volumeBar"
                      height={volumeHeight}
                      width={Math.max(candleWidth, 1)}
                      x={x - candleWidth / 2}
                      y={volumeBottom - volumeHeight}
                    />
                  </g>
                );
              })}

              {factorLinePoints ? (
                <polyline className="factorOverlayLine" points={factorLinePoints} />
              ) : null}
              {activeFactorPoint && hover ? (
                <circle
                  className="factorOverlayDot"
                  cx={xAt(hover.index)}
                  cy={factorY(activeFactorPoint.factor_value)}
                  r="3"
                />
              ) : null}

              {activeBar && hover ? (
                <g className="crosshair">
                  <line x1={xAt(hover.index)} x2={xAt(hover.index)} y1={priceTop} y2={factorBottom} />
                  <line
                    x1={CHART.marginLeft}
                    x2={CHART.width - CHART.marginRight}
                    y1={priceY(activeBar.close)}
                    y2={priceY(activeBar.close)}
                  />
                </g>
              ) : null}
            </svg>

            {activeBar && hover ? (
              <div
                className="chartTooltip"
                style={{
                  left: `${clamp(hover.x + 14, 8, 560)}px`,
                  top: `${clamp(hover.y + 14, 8, 250)}px`
                }}
              >
                <div className="tooltipHeader">{activeBar.date}</div>
                <dl>
                  <dt>OPEN</dt>
                  <dd>{formatNumber(activeBar.open)}</dd>
                  <dt>HIGH</dt>
                  <dd>{formatNumber(activeBar.high)}</dd>
                  <dt>LOW</dt>
                  <dd>{formatNumber(activeBar.low)}</dd>
                  <dt>CLOSE</dt>
                  <dd>{formatNumber(activeBar.close)}</dd>
                  <dt>VOL</dt>
                  <dd>{formatVolume(activeBar.volume)}</dd>
                  <dt>FACTOR</dt>
                  <dd>
                    {activeFactorPoint
                      ? formatFactor(activeFactorPoint.factor_value, activeFactor)
                      : "-"}
                  </dd>
                </dl>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}
