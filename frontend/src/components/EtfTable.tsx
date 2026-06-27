import type { EtfBasic } from "../types/etf";

type EtfTableProps = {
  etfs: EtfBasic[];
  totalCount: number;
  activeTheme: string;
  themeOptions: Array<{ theme: string; count: number }>;
  selectedSymbol: string | null;
  onThemeChange: (theme: string) => void;
  onSelect: (symbol: string) => void;
};

function formatNumber(value: number | null, fractionDigits = 2) {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return value.toLocaleString("zh-CN", { maximumFractionDigits: fractionDigits });
}

function formatAmount(value: number | null) {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  if (value >= 100000000) {
    return `${(value / 100000000).toLocaleString("zh-CN", { maximumFractionDigits: 2 })} 亿`;
  }
  if (value >= 10000) {
    return `${(value / 10000).toLocaleString("zh-CN", { maximumFractionDigits: 2 })} 万`;
  }
  return formatNumber(value, 0);
}

export function EtfTable({
  etfs,
  totalCount,
  activeTheme,
  themeOptions,
  selectedSymbol,
  onThemeChange,
  onSelect,
}: EtfTableProps) {
  return (
    <section className="section tableSection">
      <div className="sectionHeader">
        <div>
          <p className="eyebrow">UNIVERSE</p>
          <h2>流动性 Top 100 ETF</h2>
        </div>
        <span className="sectionMeta">
          {etfs.length.toLocaleString("zh-CN")} / {totalCount.toLocaleString("zh-CN")} symbols
        </span>
      </div>
      <div className="themeFilter" aria-label="主题筛选">
        {themeOptions.map((option) => (
          <button
            className={option.theme === activeTheme ? "active" : ""}
            key={option.theme}
            onClick={() => onThemeChange(option.theme)}
            type="button"
          >
            <span>{option.theme}</span>
            <strong>{option.count}</strong>
          </button>
        ))}
      </div>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>主题</th>
              <th>最新价</th>
              <th>涨跌幅</th>
              <th>成交量</th>
              <th>成交额</th>
              <th>来源</th>
            </tr>
          </thead>
          <tbody>
            {etfs.map((item) => (
              <tr
                className={item.symbol === selectedSymbol ? "selected" : ""}
                key={item.symbol}
                onClick={() => onSelect(item.symbol)}
              >
                <td>{item.symbol}</td>
                <td>{item.name}</td>
                <td>{item.theme}</td>
                <td>{formatNumber(item.latest_price, 3)}</td>
                <td className={(item.pct_chg ?? 0) >= 0 ? "positive" : "negative"}>
                  {item.pct_chg === null ? "-" : `${formatNumber(item.pct_chg, 2)}%`}
                </td>
                <td>{formatAmount(item.volume)}</td>
                <td>{formatAmount(item.amount)}</td>
                <td>{item.provider}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
