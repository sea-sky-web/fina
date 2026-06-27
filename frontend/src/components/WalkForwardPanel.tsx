import { AlertTriangle, BarChart3, CheckCircle2, Layers, Play } from "lucide-react";
import type { WalkForwardResult, WalkForwardWindow } from "../types/etf";

type WalkForwardPanelProps = {
  result: WalkForwardResult | null;
  isLoading: boolean;
  isStale: boolean;
  onRun: () => void;
};

function formatPct(value: number | null, digits = 2) {
  if (value === null || Number.isNaN(value)) return "-";
  return `${(value * 100).toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })}%`;
}

function formatNumber(value: number | null, digits = 2) {
  if (value === null || Number.isNaN(value)) return "-";
  return value.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function OosIsComparison({ label, oos, is }: { label: string; oos: number | null; is: number | null }) {
  const gap = oos !== null && is !== null ? oos - is : null;
  return (
    <span>
      {label}
      <strong className={gap !== null && gap < 0 ? "negative" : "positive"}>
        {formatPct(oos)}
      </strong>
      <span className="metricNote">IS {formatPct(is)}</span>
    </span>
  );
}

function WindowCard({ window: w, index }: { window: WalkForwardWindow; index: number }) {
  return (
    <div className="wfWindowCard">
      <div className="wfWindowHeader">
        <span>W{index + 1}</span>
        <span>{w.train_start} → {w.test_end}</span>
        <span>{w.selected_factors.length} factors</span>
      </div>
      <div className="wfWindowMetrics">
        <span>OOS Ann<strong>{formatPct(w.test_metrics.annualized_return)}</strong></span>
        <span>MaxDD<strong>{formatPct(w.test_metrics.max_drawdown)}</strong></span>
        <span>Sharpe<strong>{formatNumber(w.test_metrics.sharpe_like)}</strong></span>
      </div>
    </div>
  );
}

export function WalkForwardPanel({ result, isLoading, isStale, onRun }: WalkForwardPanelProps) {
  if (isLoading) {
    return (
      <section className="section">
        <div className="sectionHeader">
          <div>
            <p className="eyebrow">WALK-FORWARD</p>
            <h2>滚动窗口样本外验证</h2>
          </div>
          <button className="sectionActionButton" disabled title="正在计算 Walk-forward" type="button">
            <Play size={13} />
            计算中...
          </button>
        </div>
        <div className="backtestEmpty">正在计算滚动窗口样本外表现...</div>
      </section>
    );
  }

  if (!result || result.windows.length === 0) {
    return (
      <section className="section">
        <div className="sectionHeader">
          <div>
            <p className="eyebrow">WALK-FORWARD</p>
            <h2>滚动窗口样本外验证</h2>
          </div>
          <button
            className="sectionActionButton"
            onClick={onRun}
            title="运行滚动窗口样本外验证"
            type="button"
          >
            <Play size={13} />
            运行 WF
          </button>
        </div>
        <div className="backtestEmpty">
          {result?.data_notes?.[0] ?? "点击运行 WF 生成滚动窗口样本外验证结果。"}
        </div>
      </section>
    );
  }

  const { config, windows, oos_metrics, is_metrics, factor_stability, overfit_warning } = result;
  const oosAnn = oos_metrics.annualized_return;
  const isAnn = is_metrics.annualized_return;
  const spread = oosAnn !== null && isAnn !== null ? oosAnn - isAnn : null;
  const isSevereOverfit = spread !== null && spread < -0.10;

  return (
    <section className="section">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">WALK-FORWARD</p>
          <h2>滚动窗口样本外验证</h2>
        </div>
        <div className="sectionActions">
          <span className="sectionMeta">
            {isStale ? "参数已修改" : `${config.train_months}M train / ${config.test_months}M test / ${config.step_months}M step`}
          </span>
          <button
            className="sectionActionButton"
            onClick={onRun}
            title="按当前参数重新运行 Walk-forward"
            type="button"
          >
            <Play size={13} />
            重新运行 WF
          </button>
        </div>
      </div>

      <div className={`wfVerdict ${isSevereOverfit ? "wfWarning" : "wfOk"}`}>
        {isSevereOverfit ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
        <span>{overfit_warning}</span>
      </div>

      <div className="wfMetricGrid">
        <div className="wfMetricCard">
          <h3><BarChart3 size={14} /> 样本外 (OOS)</h3>
          <div className="metricGrid compact">
            <span>年化收益<strong>{formatPct(oos_metrics.annualized_return)}</strong></span>
            <span>年化波动<strong>{formatPct(oos_metrics.annualized_volatility)}</strong></span>
            <span>最大回撤<strong>{formatPct(oos_metrics.max_drawdown)}</strong></span>
            <span>Sharpe<strong>{formatNumber(oos_metrics.sharpe_like)}</strong></span>
            <span>日胜率<strong>{formatPct(oos_metrics.win_rate_daily)}</strong></span>
            <span>终值<strong>{formatNumber(oos_metrics.final_equity, 3)}</strong></span>
          </div>
        </div>

        <div className="wfMetricCard">
          <h3><BarChart3 size={14} /> 样本内 (IS) 对比</h3>
          <div className="metricGrid compact">
            <OosIsComparison label="年化收益" oos={oos_metrics.annualized_return} is={is_metrics.annualized_return} />
            <OosIsComparison label="年化波动" oos={oos_metrics.annualized_volatility} is={is_metrics.annualized_volatility} />
            <OosIsComparison label="最大回撤" oos={oos_metrics.max_drawdown} is={is_metrics.max_drawdown} />
            <OosIsComparison label="Sharpe" oos={oos_metrics.sharpe_like} is={is_metrics.sharpe_like} />
            <span>
              OOS/IS 差
              <strong className={spread !== null && spread < 0 ? "negative" : "positive"}>
                {formatPct(spread)}
              </strong>
            </span>
            <span>调仓<strong>{oos_metrics.rebalance_count} / {is_metrics.rebalance_count}</strong></span>
          </div>
        </div>

        <div className="wfMetricCard">
          <h3><Layers size={14} /> 因子稳定性</h3>
          <div className="metricGrid compact">
            <span>
              选中一致性
              <strong>{(factor_stability * 100).toFixed(0)}%</strong>
            </span>
            <span>
              窗口数
              <strong>{windows.length}</strong>
            </span>
            {Object.entries(result.weight_stability).slice(0, 4).map(([name, cv]) => (
              <span key={name}>
                {name.slice(0, 12)}
                <strong>{cv !== null ? `CV ${(cv * 100).toFixed(0)}%` : "-"}</strong>
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="wfWindowList">
        <h3>各窗口详情（{windows.length} 个）</h3>
        <div className="wfWindows">
          {windows.slice(0, 8).map((w, i) => (
            <WindowCard key={`${w.train_start}`} window={w} index={i} />
          ))}
        </div>
      </div>

      {result.data_notes.length > 0 ? (
        <div className="riskNotePanel">
          <h3><AlertTriangle size={14} /> 说明</h3>
          {result.data_notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      ) : null}
    </section>
  );
}
