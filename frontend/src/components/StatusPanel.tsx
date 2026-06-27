import { Database, RefreshCcw } from "lucide-react";

import type { DataStatus } from "../types/etf";

type StatusPanelProps = {
  statuses: DataStatus[];
  isRefreshing: boolean;
  onRefresh: () => void;
};

export function StatusPanel({ isRefreshing, onRefresh, statuses }: StatusPanelProps) {
  const hasStaleData = statuses.some((item) => item.status === "stale" || item.status === "error");

  return (
    <section className="section">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">DATA HEALTH</p>
          <h2>采集状态</h2>
        </div>
        <button
          className="iconButton"
          disabled={isRefreshing}
          onClick={onRefresh}
          title="重新采集 Top 100 ETF 数据"
          type="button"
        >
          <RefreshCcw className={isRefreshing ? "spin" : ""} size={18} />
        </button>
      </div>
      {hasStaleData ? (
        <div className="warningBanner">当前展示缓存数据，请查看状态说明。</div>
      ) : null}
      <div className="statusGrid">
        {statuses.map((item) => (
          <article className="statusCard" key={`${item.provider}-${item.dataset}`}>
            <div className="statusTitle">
              <Database size={18} />
              <span>{item.dataset}</span>
            </div>
            <strong>{item.rows.toLocaleString("zh-CN")}</strong>
            <p>{item.message}</p>
            <span className={`statusBadge ${item.status}`}>{item.status}</span>
          </article>
        ))}
      </div>
    </section>
  );
}
