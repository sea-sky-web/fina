# ETF 因子研究框架设计文档

> 版本: 2.1 | 日期: 2026-06-07 | 基于 Quantopian 研究范式适配改造 | 增加实用化缺口分析与 Walk-forward 框架

## 一、项目定位

Fina 是一个**个人自用的沪深 ETF 量化因子研究终端**。核心目标不是提供交易信号或投资建议，而是让使用者能够：

1. **可靠地**采集和清洗沪深 ETF 数据
2. **系统性地**计算、处理和评估因子
3. **可解释地**理解因子行为（区分度、稳定性、衰减）
4. **可复现地**验证基于因子的选择规则在历史上的表现

不做什么：实盘交易、自动下单、面向第三方用户的投资推荐。

---

## 二、业界参考框架：Quantopian 研究范式

Quantopian 将量化研究拆解为六个独立且可组合的阶段。每个阶段有明确的输入、输出和评估标准。这也是 Alphalens + Zipline + Pyfolio 三件套的底层设计哲学。

### 2.1 Pipeline 全貌

```
┌─────────────────────────────────────────────────────────────────┐
│                        RESEARCH PIPELINE                         │
│                                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐                 │
│  │ Universe │ → │  Alpha   │ → │  Evaluation  │ ← ★ 核心环节    │
│  │ 可投资池 │   │ 因子计算 │   │  因子评估    │                 │
│  └──────────┘   └──────────┘   └──────┬───────┘                 │
│                                       │ 通过评估?                │
│                               ┌───────▼───────┐                 │
│                               │    Signal     │                 │
│                               │   信号合成    │                 │
│                               └───────┬───────┘                 │
│                                       │                          │
│  ┌──────────┐   ┌──────────┐   ┌──────▼───────┐                 │
│  │Monitoring│ ← │Attribut. │ ← │  Portfolio   │                 │
│  │ 监控预警 │   │ 绩效归因 │   │  组合构建    │                 │
│  └──────────┘   └──────────┘   └──────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 各阶段定义

| 阶段 | 英文 | 核心问题 | 关键指标 | 对应工具 |
|------|------|---------|---------|---------|
| **可投资池** | Universe | 哪些资产可以买？何时可以买？ | 时点截面、流动性门槛 | Zipline Pipeline |
| **因子计算** | Alpha | 这个指标能否区分未来表现？ | 因子值序列 | Pipeline API |
| **因子评估** | Evaluation | 因子质量如何？是否稳定？ | IC / ICIR / 分位数收益差 / 换手率 | **Alphalens** |
| **信号合成** | Signal | 多个因子如何合并？ | 合成权重、相关性惩罚 | 自定义 |
| **组合构建** | Portfolio | 如何配置权重？ | 换手率、容量、约束 | Zipline / Riskfolio |
| **绩效归因** | Attribution | 收益来源是什么？ | 因子收益 vs 特质收益 | **Pyfolio** |

### 2.3 Alphalens 因子评估体系（核心参考）

Alphalens 是 Quantopian 生态中专做因子评估的库。它的设计是我们重构 Fina 因子系统的最重要参考。其 API 设计遵循一个核心流程：

```python
# Alphalens 标准流程（简化）
# 输入: factor (MultiIndex: date × asset), prices, groupby (optional)

# Step 1: 数据清洗和对齐
factor_data = get_clean_factor_and_forward_returns(
    factor,
    prices,
    periods=(1, 5, 20),      # 前瞻周期（天）
    quantiles=5,              # 分组数
    groupby=sector,           # 行业中性化分组键
    max_loss=0.35,            # 最大允许缺失比例
)

# Step 2: 一键生成完整 tear sheet
create_full_tear_sheet(factor_data)
# 输出以下分析模块:
```

拆解 Alphalens 的 tear sheet，它输出以下诊断板块：

#### A. Returns Analysis（收益分析）
```
┌──────────────────────────────────────────────────┐
│  Mean Period Wise Return By Factor Quantile      │
│  ┌────────────────────────────────────────────┐  │
│  │  1D     5D     20D                         │  │
│  │  Q1 ██  Q1 ███  Q1 ████  ← Top quantile   │  │
│  │  Q2 █   Q2 ██   Q2 ███                     │  │
│  │  Q3 █   Q3 █    Q3 ██                      │  │
│  │  Q4 █   Q4 █    Q4 █                       │  │
│  │  Q5 █   Q5 █    Q5 █   ← Bottom quantile   │  │
│  └────────────────────────────────────────────┘  │
│  ★ 理想形态: 收益单调递减 (Q1 > Q2 > ... > Q5)  │
│  ★ 关注: Q1-Q5 spread 大小和显著性               │
└──────────────────────────────────────────────────┘
```

#### B. Information Coefficient Analysis（IC 分析）
```
┌──────────────────────────────────────────────────┐
│  IC 统计量                                       │
│  ┌────────────────────────────────────────────┐  │
│  │  Rank IC Mean:   0.045                     │  │
│  │  Rank IC Std:    0.12                      │  │
│  │  ICIR:           0.045 / 0.12 = 0.375      │  │
│  │  IC > 0 Ratio:   62%                       │  │
│  │  t-stat(IC):     2.8                       │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  IC 月度热力图                         IC 衰减曲线│
│  ┌─────────────────────────┐    ┌──────────────┐ │
│  │  Jan Feb Mar ... Dec    │    │              │ │
│  │   +   +   -   ...  +   │    │ IC           │ │
│  │  ...                    │    │  │\          │ │
│  └─────────────────────────┘    │  │ \___      │ │
│                                  │  1D 5D 20D  │ │
│                                  └──────────────┘ │
└──────────────────────────────────────────────────┘
```

IC 是因子评估的"北极星"指标：
- **Pearson IC**: corr(factor_value, forward_return)，线性相关
- **Rank IC (Spearman)**: corr(rank(factor_value), rank(forward_return))，更稳健，**优先使用**
- **ICIR**: IC_mean / IC_std，同时衡量预测力和稳定性。一般认为 ICIR > 0.5 是可用的因子
- **IC Decay**: IC 随前瞻周期的衰减速度，衡量因子的"保质期"

#### C. Turnover Analysis（换手率分析）
```
┌──────────────────────────────────────────────────┐
│  Factor Rank Autocorrelation                     │
│  ┌────────────────────────────────────────────┐  │
│  │  Lag 1:  0.92                              │  │
│  │  Lag 5:  0.78                              │  │
│  │  Lag 20: 0.55                              │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  Quantile Turnover Heatmap                       │
│  ┌────────────────────────────────────────────┐  │
│  │  迁移矩阵: 本月 Q1 → 下月 Q1/Q2/Q3/Q4/Q5  │  │
│  │  Q1: 65% 20% 10%  4%  1%                  │  │
│  │  Q2: 18% 50% 22%  8%  2%                  │  │
│  │  ...                                       │  │
│  └────────────────────────────────────────────┘  │
│  ★ 高自相关 → 低换手 → 低交易成本                │
│  ★ 低自相关 → 排名跳动大 → 信号噪声比差           │
└──────────────────────────────────────────────────┘
```

#### D. Factor Correlation（因子相关性）
```
┌──────────────────────────────────────────────────┐
│  Factor Correlation Matrix                       │
│  ┌────────────────────────────────────────────┐  │
│  │         mom  vol  liq  dd   rar  trend     │  │
│  │  mom    1.0  0.1  0.2  0.6  0.85 0.75     │  │
│  │  vol         1.0  0.1 -0.3 -0.2 -0.1      │  │
│  │  liq              1.0  0.1  0.15 0.2      │  │
│  │  dd                    1.0  0.55 0.5      │  │
│  │  rar                         1.0  0.7      │  │
│  │  trend                            1.0      │  │
│  └────────────────────────────────────────────┘  │
│  ★ |ρ| > 0.6 的因子对高度冗余，应合并或择一       │
│  ★ 目标是保持因子池的相关性普遍 < 0.4             │
└──────────────────────────────────────────────────┘
```

### 2.4 Pyfolio 归因体系

Pyfolio 做的是事后分析——回答"收益从哪来"。核心输出：

| 模块 | 内容 | 我们需要的 |
|------|------|-----------|
| **Returns tear sheet** | 累计收益、滚动 Sharpe、月度收益热力图 | ✓ |
| **Factor regression** | 用日收益回归因子暴露，分解 α vs β | ✓ 核心 |
| **Event risk** | 回撤事件分析 | ✓ |
| **Round-trip analysis** | 每笔"买入→卖出"的收益分布 | ETF 等权再平衡场景不适用 |
| **Turnover** | 持仓换手率时间序列 | ✓ |

---

## 三、当前项目差距诊断

### 3.1 差距矩阵

```
业界标准流程:          当前项目状态:               差距:

Universe    ████████   ✓ 按成交额选 Top-N          ✗ 缺少历史时点池(回测用)
Alpha       ████████   ✓ 7个因子, Factor ABC       △ 缺去极值/标准化/中性化
Processing  ░░░░░░░░   ✗ 完全缺失                  ★ 第一需要补的
Evaluation  ░░░░░░░░   ✗ 完全缺失                  ★ ★ 最核心缺失
Signal      ████░░░░   △ 有固定权重合成             ✗ 无IC加权,无因子筛选
Correlation ░░░░░░░░   ✗ 完全缺失                  ★ 必须补（当前权重无依据）
Portfolio   ████░░░░   △ 仅等权+月度调仓            △ 可接受
Attribution ░░░░░░░░   ✗ 完全缺失                  △ 后续补
Monitoring  ░░░░░░░░   ✗ 完全缺失                  △ 后续补
```

### 3.2 当前最致命的结构性问题

1. **因子处理缺失**：原始因子值直接用于排名，没有去极值/标准化/中性化。一个极端异常值就能扭曲整个横截面排名。

2. **因子评估缺失**：没有任何 IC 分析。你无法回答"这个因子有没有预测力"这个问题——你在回测一个你甚至不知道是否有效的因子。

3. **信号合成无依据**：6 个因子中 3 个动量变体合计权重 0.70，且没有任何相关性分析来证明它们确实是不同维度的信息。

4. **有诊断面板但没有评估框架**：当前 `FactorDiagnostics` 做了分布统计和 forward return，但缺少 IC 统计量、相关性矩阵、因子衰减——这些才是评估的核心。

---

## 四、目标架构设计

### 4.1 模块总览

```
backend/app/
│
├── factors/                         # ★ 重构后
│   ├── base.py                      #   Factor ABC (保留增强)
│   ├── registry.py                  #   注册表 (保留)
│   │
│   ├── implementations/             #   因子实现 (迁移+扩展)
│   │   ├── __init__.py
│   │   ├── momentum.py              #     60日动量
│   │   ├── volatility.py            #     30日波动率
│   │   ├── turnover.py              #     20日均成交额
│   │   ├── drawdown.py              #     60日最大回撤
│   │   ├── risk_adjusted_return.py  #     60日风险调整收益
│   │   ├── liquidity_stability.py   #     20日流动性稳定性
│   │   ├── trend_strength.py        #     20/60日趋势强度
│   │   └── etf_specific/            #     ETF 特有因子 (新增)
│   │       ├── __init__.py
│   │       ├── tracking_error.py    #       跟踪误差
│   │       ├── premium_discount.py  #       折溢价率
│   │       └── fund_flow.py         #       资金流向/规模变动
│   │
│   └── processing/                  #   因子处理管线 (★ 新增)
│       ├── __init__.py
│       ├── pipeline.py              #     编排器: raw → winsorize → standardize → neutralize
│       ├── outliers.py              #     去极值: MAD / percentile clip
│       ├── standardize.py           #     截面 Z-score 标准化
│       └── neutralize.py            #     主题/行业中性化
│
├── evaluation/                      # 因子评估引擎 (★ ★ 新增，最大模块)
│   ├── __init__.py
│   ├── ic_analysis.py               #   Rank IC / Pearson IC + t-stat
│   ├── ic_decay.py                  #   IC 衰减（多前瞻周期）
│   ├── quantile_analysis.py         #   分位数分组收益 + spread 单调性
│   ├── correlation.py               #   因子相关性矩阵 + 聚类
│   ├── turnover.py                  #   排名自相关 + 分组迁移矩阵
│   ├── regime.py                    #   牛熊市分阶段 IC
│   └── report.py                    #   生成标准化评估报告 → FactorEvaluationResult
│
├── synthesis/                       # 信号合成 (★ 重新设计)
│   ├── __init__.py
│   ├── weighting.py                 #   ICIR 加权 / IC 加权 / 等权
│   ├── combination.py               #   多因子合成 + 相关性惩罚
│   └── selection.py                 #   因子筛选（去冗余、去无效）
│
├── backtest/                        # 回测 + 归因 (重构)
│   ├── __init__.py
│   ├── universe.py                  #   时点敏感的 ETF 池 (修正前视偏差)
│   ├── portfolio.py                 #   组合构建: 等权 / ICIR 加权配置
│   ├── attribution.py               #   绩效归因: 因子收益 vs 特质收益
│   └── metrics.py                   #   收益 + 风险 + 归因指标
│
├── monitoring/                      # 监控 (★ 新增)
│   ├── __init__.py
│   ├── factor_health.py             #   因子覆盖度 / 衰减 / 异常预警
│   └── alerts.py                    #   数据质量告警
│
├── services/                        # 服务层 (精简)
│   ├── etf_service.py               #   ETF 查询 (保留)
│   ├── status_service.py            #   数据状态 (保留)
│   ├── refresh_service.py           #   数据刷新 (保留)
│   ├── factor_service.py            #   因子服务 (★ 大幅重构)
│   ├── evaluation_service.py        #   评估服务 (★ 新增)
│   ├── signal_service.py            #   信号服务 (重构)
│   ├── backtest_service.py          #   回测服务 (重构)
│   └── theme_classifier.py          #   主题分类器 (保留)
│
├── api/v1/                          # API 路由
│   ├── etfs.py                      #   保留
│   ├── factors.py                   #   重构: 因子CRUD + 评估报告
│   ├── evaluation.py                #   ★ 新增: 评估报告端点
│   ├── signals.py                   #   重构: 基于新合成逻辑
│   ├── backtests.py                 #   重构: 基于新回测框架
│   ├── refresh.py                   #   保留
│   └── status.py                    #   保留
│
├── models/
│   ├── etf.py                       #   数据模型 (增强: +评估结果模型)
│   └── evaluation.py                #   ★ 新增: 评估结果模型
│
├── storage/                         # 保留 + 增强
│   ├── parquet_store.py             #   保留
│   ├── duckdb_client.py             #   保留
│   └── cache.py                     #   ★ 新增: 简单内存缓存
│
└── core/
    └── config.py                    #   增强: +评估参数配置
```

### 4.2 数据流总图

```
                                    ┌──────────────────┐
                                    │   AKShare        │
                                    └────────┬─────────┘
                                             │
                              ┌──────────────▼──────────────┐
                              │       Collectors            │
                              │  akshare_collector.py       │
                              └──────────────┬──────────────┘
                                             │
                              ┌──────────────▼──────────────┐
                              │      Normalizers            │
                              │  raw → clean parquet         │
                              │  etf_basic / etf_daily       │
                              └──────────────┬──────────────┘
                                             │
                                             │ clean parquet
                                             │
┌────────────────────────────────────────────▼────────────────────────────────────────────┐
│                                                                                          │
│   ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐                       │
│   │  factors/    │    │   evaluation/     │    │   synthesis/     │                       │
│   │  implementations │   │   ★ 因子评估     │    │   ★ 信号合成     │                       │
│   │  ★ 因子计算   │    │                  │    │                  │                       │
│   │              │    │  IC分析           │    │  ICIR加权        │                       │
│   │  momentum    │    │  Quantile收益     │    │  相关性惩罚       │                       │
│   │  volatility  │───→│  相关性矩阵        │───→│  因子筛选         │───→ research_score │
│   │  turnover    │    │  换手率           │    │                  │                       │
│   │  ...         │    │  IC衰减           │    │                  │                       │
│   └──────┬───────┘    └──────────────────┘    └──────────────────┘                       │
│          │                                                                                │
│          │   ┌──────────────┐                                                            │
│          │   │  processing/ │  ← 处理管线嵌入在 compute → evaluate 之间                      │
│          │   │  去极值       │                                                            │
│          │   │  标准化       │                                                            │
│          │   │  中性化       │                                                            │
│          │   └──────────────┘                                                            │
│          │                                                                                │
└──────────┼────────────────────────────────────────────────────────────────────────────────┘
           │
           │ research_score
           │
┌──────────▼──────────────────────────────────────────────────────────────────┐
│                                                                              │
│   ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐           │
│   │  backtest/   │    │  monitoring/     │    │  api/            │           │
│   │              │    │                  │    │                  │           │
│   │  universe    │    │  覆盖度           │    │  /factors        │           │
│   │  portfolio   │    │  IC衰减预警       │    │  /evaluation     │           │
│   │  attribution │    │  数据质量         │    │  /signals        │           │
│   │  metrics     │    │                  │    │  /backtests      │           │
│   └──────────────┘    └──────────────────┘    └──────────────────┘           │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 五、模块详细设计

### 5.1 Factor Processing Pipeline（因子处理管线）

#### 设计原理

原始因子值直接从行情数据算出后，不能直接用于排名和评估。标准流程包含三步处理：

```
Raw Factor Value
    │
    ▼
┌─────────────┐
│ 1. 去极值    │  → MAD (Median Absolute Deviation) 或 Percentile Clip
│   Winsorize  │    目的: 消除极端值对截面排名的扭曲
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 2. 标准化    │  → Cross-sectional Z-score
│ Standardize │    目的: 让不同量纲的因子可比较、可合成
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 3. 中性化    │  → 对 theme 做回归取残差，或在 theme 内独立排名
│ Neutralize  │    目的: 消除行业/主题偏配，让因子度量的是"同类中的相对优劣"
└──────┬──────┘
       │
       ▼
  Clean Factor
  (ready for evaluation)
```

#### API 设计

```python
# factors/processing/pipeline.py

def process_factor(
    factor_values: pd.Series,
    method: str = "mad",
    mad_n: float = 5.0,
    standardize: bool = True,
    groupby: pd.Series | None = None,
    neutralize_method: str = "residual",
) -> pd.Series:
    """
    因子处理管线。

    Args:
        factor_values: 原始因子值，index 为 (date, symbol) MultiIndex
        method: 去极值方法，"mad" | "percentile"
        mad_n: MAD 倍数阈值，默认 5
        standardize: 是否截面标准化
        groupby: 分组键 (如 theme)，提供则执行中性化
        neutralize_method: "residual" (回归残差) | "intra_group_rank" (组内排名)

    Returns:
        处理后的因子值，保持原始 index

    Example:
        themes = get_etf_themes()  # Series[symbol] → theme
        clean = process_factor(
            raw_momentum,
            groupby=themes,
            neutralize_method="intra_group_rank"
        )
    """
```

#### 去极值方法选择

| 方法 | 适用场景 | 公式 |
|------|---------|------|
| **MAD** | 厚尾分布、存在异常跳跃 | `clip(x, median ± n * 1.4826 * MAD)` |
| **Percentile** | 分布已知、需要保留更多信息 | `clip(x, P1, P99)` |
| **Sigma** | 近似正态分布 | `clip(x, mean ± n * std)` |

ETF 因子（尤其是成交额类）通常有厚尾，选择 **MAD** 作为默认方法。

#### 中性化实现

```python
# factors/processing/neutralize.py

def sector_neutralize_residual(
    factor_values: pd.Series,
    groups: pd.Series,
) -> pd.Series:
    """
    回归法中性化: factor ~ group_dummies, 取残差
    残差 = 剔除了行业平均差异后的"纯因子暴露"
    """
    # 对每个 date 截面独立做
    ...

def intra_group_rank(
    factor_values: pd.Series,
    groups: pd.Series,
) -> pd.Series:
    """
    组内排名法: 在每个 group 内独立计算 percentile rank
    结果是一个 0~1 的分数，表示在同类中的相对位置
    ★ 推荐用于 ETF 场景——更直观，不依赖线性假设
    """
    ...
```

#### 配置项

```python
# core/config.py 新增

class Settings:
    # Factor processing
    factor_outlier_method: str = "mad"       # "mad" | "percentile" | "none"
    factor_outlier_mad_n: float = 5.0
    factor_standardize: bool = True
    factor_neutralize: bool = True           # 是否启用主题中性化
    factor_neutralize_method: str = "intra_group_rank"
```

#### 与现有因子系统的整合

处理管线不修改原始 `Factor.compute()` 的返回值，而是作为**后处理步骤**嵌入到因子存储和评估流程中：

```python
# 旧流程:
# Factor.compute(daily) → raw_factor → rebuild_factors 直接存

# 新流程:
# Factor.compute(daily) → raw_factor → process_factor() → clean_factor → 存为 factors_clean.parquet
#                                                      ↘ raw_factor → 存为 factors_raw.parquet (备查)
```

文件布局：

| 文件 | 内容 | 用途 |
|------|------|------|
| `data/clean/factors.parquet` | 原始因子值 | 保留现有格式，向后兼容 |
| `data/clean/factors_processed.parquet` | 处理后因子值 | 评估和排名的输入 |

---

### 5.2 Factor Evaluation Engine（因子评估引擎）

#### 核心概念

| 指标 | 英文 | 公式 | 含义 | 好因子的标准 |
|------|------|------|------|-------------|
| **Rank IC** | Rank Information Coefficient | `corr(rank(factor), rank(forward_return))` | 因子排序和未来收益排序的相关性 | \|IC\| > 0.03, 方向稳定 |
| **ICIR** | IC Information Ratio | `mean(IC) / std(IC)` | 预测力/波动率——同时衡量效果和稳定性 | ICIR > 0.3 |
| **IC > 0 Ratio** | IC Win Rate | `count(IC > 0) / total_periods` | IC 为正的样本占比 | > 55% |
| **Quantile Spread** | 分位数收益差 | `mean_return(Q1) - mean_return(Q5)` | Top 组和 Bottom 组的年化收益差 | > 5% 且有单调性 |
| **Factor Decay** | IC 衰减 | IC at horizon=1D, 5D, 10D, 20D | 预测力随持有期延长如何衰减 | 衰减慢 = 信号持久 |
| **Rank Autocorr** | 排名自相关 | `corr(rank_t, rank_{t-1})` | 排名在相邻周期的稳定性 | 0.85~0.95 (太低信号噪, 太高无新信息) |
| **Pairwise Corr** | 因子相关性 | `corr(factor_A, factor_B)` 截面均值 | 两个因子是否度量同一维度 | \|ρ\| < 0.6 |
| **Regime IC** | 分阶段 IC | 牛/熊/震荡市分别计算 IC | 因子在不同市场环境下的表现差异 | 不只在牛市有用 |

#### 数据模型

```python
# models/evaluation.py

class FactorICStats(BaseModel):
    """单个因子的 IC 统计"""
    factor_name: str
    period_start: date
    period_end: date
    num_periods: int               # 评估周期数
    # IC
    rank_ic_mean: float
    rank_ic_std: float
    icir: float                    # = rank_ic_mean / rank_ic_std
    ic_pos_ratio: float            # IC > 0 的周期占比
    ic_t_stat: float               # t-statistic for IC ≠ 0
    ic_series: list[dict]          # [{date, ic_value}, ...] 用于绘图
    # IC Decay
    ic_by_horizon: dict[int, float]  # {5: 0.045, 10: 0.038, 20: 0.021, 60: 0.008}


class FactorQuantileReturns(BaseModel):
    """分位数收益分析"""
    factor_name: str
    horizon_days: int              # 前瞻周期
    num_quantiles: int = 5
    quantile_returns: dict[str, float]  # {"Q1": 0.08, "Q2": 0.05, ..., "Q5": -0.02}
    spread: float                  # Q1_mean - Q5_mean
    is_monotonic: bool             # 收益是否随分位单调
    quantile_series: list[dict]    # [{date, Q1_return, Q2_return, ...}] 用于绘图


class FactorCorrelationMatrix(BaseModel):
    """因子相关性矩阵"""
    date: date                     # 评估截面日期
    factor_names: list[str]
    matrix: list[list[float]]      # N × N 相关系数矩阵
    redundant_pairs: list[dict]    # [{factor_a, factor_b, correlation}], |ρ| > 0.6


class FactorTurnoverStats(BaseModel):
    """因子换手率统计"""
    factor_name: str
    rank_autocorr: dict[int, float]  # {1: 0.92, 5: 0.78, 20: 0.55}
    avg_turnover: float              # 平均分位组迁移率
    migration_matrix: list[list[float]]  # 5×5 迁移矩阵（上期分位 → 本期分位）


class FactorEvaluationReport(BaseModel):
    """★ 核心: 单个因子的完整评估报告"""
    factor_name: str
    generated_at: datetime
    period_start: date
    period_end: date
    num_assets_avg: float
    # 子模块
    ic: FactorICStats
    quantile_returns: dict[int, FactorQuantileReturns]  # key = horizon
    correlations: FactorCorrelationMatrix | None
    turnover: FactorTurnoverStats | None
    warnings: list[str]              # 自动检测的问题
    # 总体判断
    overall_verdict: str             # "可用" / "待观察" / "不推荐单独使用"


class FactorPoolEvaluationReport(BaseModel):
    """★ 因子池整体评估报告"""
    generated_at: datetime
    individual_reports: list[FactorEvaluationReport]
    correlation_matrix: FactorCorrelationMatrix
    cluster_groups: list[dict]        # 聚类结果: [{group: "动量组", factors: [...]}]
    pool_health: str                  # "健康" / "冗余" / "因子不足"
    recommendations: list[str]        # 自动建议: "momentum_60d 与 risk_adjusted_return_60d 高度相关, 建议择一保留"
```

#### API 端点设计

```python
# api/v1/evaluation.py

GET  /api/evaluation/:factor_name/report
  # 返回单个因子的完整评估报告
  # Query: ?start=2024-01-01&end=2026-06-01&horizons=5,10,20

GET  /api/evaluation/pool-report
  # 返回因子池整体评估（包含相关性矩阵、聚类、建议）
  # 这是前端"因子评估仪表板"的主要数据源

GET  /api/evaluation/:factor_name/ic-series
  # 返回 IC 时间序列（用于前端画 IC 曲线图）

GET  /api/evaluation/:factor_name/quantile-chart?horizon=20
  # 返回分位数收益序列（用于前端画 Q1~Q5 累积收益曲线）

POST /api/evaluation/run
  # 触发全量因子评估（计算 IC、相关性矩阵等）
  # Body: {"factor_names": [...], "start": "...", "end": "...", "horizons": [5, 10, 20]}
```

#### 评估执行时机

```
┌─────────────────────────────────────────┐
│  评估触发策略                             │
│                                          │
│  1. 因子重建后自动评估                     │
│     POST /factors/rebuild               │
│       → rebuild_factors()               │
│       → run_full_evaluation()  (自动)    │
│                                          │
│  2. 手动评估（指定参数）                    │
│     POST /evaluation/run                │
│                                          │
│  3. 定时评估（后续 cron 化）                │
│     每周/每月自动跑一次全量评估              │
└─────────────────────────────────────────┘
```

---

### 5.3 Signal Synthesis（信号合成）

#### 设计原则

信号合成不是"拍权重"，而是基于评估结果做**有依据的组合**。核心原则：

1. **筛选 → 加权 → 合成**，三步分开
2. **相关性惩罚**：高相关的因子组不能简单叠加权重
3. **ICIR 决定权重**：预测力强且稳定的因子权重大
4. **可解释**：每个 ETF 的综合分数可以拆解到各因子的贡献

#### 合成流程

```
Factor Pool (N factors)
    │
    ▼
┌─────────────────┐
│ Step 1: 筛选     │  → 剔除: ICIR < 0.2 / IC不显著 / 被其他因子高度替代
│   Filter         │  → 保留 K ≤ N 个有效因子
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Step 2: 权重     │  → ICIR 归一化: w_i = ICIR_i / Σ(ICIR)
│   Weighting      │  → 相关性调整: w_i *= (1 - avg_corr_with_others)
│                  │  → 等权兜底: 如果 ICIR 数据不足, 用 1/K
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Step 3: 合成     │  → Score = Σ(w_i * percentile_i) × 100
│   Combination    │  → Attachment: 每个 ETF 的得分拆分到各因子贡献
└─────────────────┘
```

#### API 设计

```python
# synthesis/weighting.py

def icir_weights(
    evaluation_reports: list[FactorEvaluationReport],
    min_icir: float = 0.2,
) -> dict[str, float]:
    """
    基于 ICIR 的因子权重。

    w_i = max(ICIR_i, 0) / Σ(max(ICIR_j, 0))
    然后对高相关因子对应用惩罚: w_i *= (1 - 0.5 * avg_corr)
    """

def filter_factors(
    evaluation_reports: list[FactorEvaluationReport],
    min_icir: float = 0.2,
    min_ic_pos_ratio: float = 0.55,
    max_pairwise_corr: float = 0.75,
) -> list[str]:
    """筛选通过质量门槛的因子"""


# synthesis/combination.py

def synthesize_scores(
    processed_factors: pd.DataFrame,   # MultiIndex (date, symbol) → {factor: percentile}
    weights: dict[str, float],
) -> pd.DataFrame:
    """
    返回: (date, symbol) → research_score + component contributions
    """
```

#### 权重不是一成不变的

权重应该定期基于最新的评估结果重新计算——至少每月一次。这就是为什么 `evaluation/` 模块是 `synthesis/` 的前置依赖。

---

### 5.4 Backtest（回测升级）

#### 核心修正: 时点敏感的 ETF 池

当前回测的最大问题是使用同一批 ETF 回测整个历史期——这产生了前视偏差。

```python
# backtest/universe.py

def point_in_time_universe(
    target_date: date,
    daily_data: pd.DataFrame,
    top_n: int = 100,
    min_history_days: int = 60,
) -> list[str]:
    """
    在 target_date 时点，用当时可用的信息构建 ETF 池。

    规则:
    1. 只使用 target_date 之前的数据
    2. target_date 之前有至少 min_history_days 个交易日
    3. 按 target_date 前 20 日均成交额排序取 top_n
    4. 排除 target_date 之后才上市的 ETF

    ★ 这就是"时点敏感"的含义——回测每个调仓日使用当时真实可用的 ETF 池
    """
```

#### 回测增强

| 增强项 | 当前状态 | 目标状态 |
|--------|---------|---------|
| Universe | 固定 Top-N | 时点敏感动态池 |
| 组合构建 | 仅等权 | 等权 / ICIR 加权 / 风险平价 |
| 调仓频率 | 仅月度 | 月度 / 双周 / 季度 (可配置) |
| 归因 | 无 | 因子收益分解 |
| 基准 | 510300 + 等权 | + 可自定义多个基准 |
| 样本外 | 无 | 滚动窗口: 前 N 月训练 → 后 M 月验证 |

#### 绩效归因

```python
# backtest/attribution.py

class PerformanceAttribution(BaseModel):
    """绩效归因报告"""
    total_return: float
    factor_contribution: dict[str, float]  # 各因子的收益贡献
    specific_return: float                 # 特质收益 (不能被因子解释的部分)
    sector_contribution: dict[str, float]  # 各主题的收益贡献
    r_squared: float                       # 因子模型的解释度
```

---

### 5.5 Monitoring（监控）

即使一个人用，监控也很重要——数据出问题时你会第一时间知道。

```python
# monitoring/factor_health.py

class FactorHealthCheck:
    """因子健康检查"""

    def check_coverage(self) -> dict:
        """每个因子覆盖了多少 ETF？是否突然下降？"""

    def check_ic_decay(self) -> dict:
        """IC 是否出现趋势性衰减（因子失效信号）？"""

    def check_outliers(self) -> dict:
        """最近截面是否有异常数量的极端值？"""

    def check_data_freshness(self) -> dict:
        """底层日线数据是否过期？"""
```

---

## 六、前端适配方案

### 6.1 新增页面

```
Workspaces:
  ├── 市场监控     (保留, 小幅优化)
  ├── 因子研究     (★ 大幅重构)
  │   ├── 因子评估仪表板  ← ★ 新增, 核心
  │   │   ├── IC 卡片组 (Rank IC / ICIR / Win Rate / t-stat)
  │   │   ├── IC 时序图
  │   │   ├── IC 衰减曲线
  │   │   ├── 分位数收益图 (Q1~Q5 累积收益曲线)
  │   │   └── 因子相关性热力图
  │   ├── 因子处理配置   ← ★ 新增
  │   └── 因子排名表     (保留, 增强为可选择原始/处理后因子)
  ├── 策略验证     (重构)
  │   ├── 信号合成配置 (权重透传 + 可调)
  │   ├── 回测参数面板
  │   ├── 净值曲线 + 基准对比
  │   └── 绩效归因拆解
  └── 数据健康     (保留, 增强: +因子健康卡片)
```

### 6.2 核心前端组件

| 组件 | 说明 |
|------|------|
| `ICChart` | Rank IC 时序折线图，标注 ICIR 和 t-stat |
| `ICDecayChart` | IC 随前瞻周期衰减的柱状图 |
| `QuantileReturnChart` | 5 条累积收益曲线 (Q1~Q5) |
| `CorrelationHeatmap` | 因子相关性热力图 |
| `FactorEvaluationCard` | 单个因子的评估摘要卡片 |
| `SignalCompositionPanel` | 展示各因子权重、贡献拆解 |
| `AttributionPanel` | 饼图 + 柱状图展示收益归因 |

### 6.3 TypeScript 类型扩展

```typescript
// types/evaluation.ts (新增)

interface FactorICStats {
  factor_name: string;
  period_start: string;
  period_end: string;
  num_periods: number;
  rank_ic_mean: number;
  rank_ic_std: number;
  icir: number;
  ic_pos_ratio: number;
  ic_t_stat: number;
  ic_series: Array<{ date: string; ic_value: number }>;
  ic_by_horizon: Record<number, number>;
}

interface FactorEvaluationReport {
  factor_name: string;
  generated_at: string;
  period_start: string;
  period_end: string;
  ic: FactorICStats;
  quantile_returns: Record<number, FactorQuantileReturns>;
  correlations: FactorCorrelationMatrix | null;
  turnover: FactorTurnoverStats | null;
  warnings: string[];
  overall_verdict: "可用" | "待观察" | "不推荐单独使用";
}
```

---

## 七、实施计划

### Phase 1: Factor Processing Pipeline（预计 2-3 天）

**目标**: 原始因子值 → 处理好可评估的因子值

```
Day 1-2: factors/processing/
  ├── outliers.py     (MAD 去极值)
  ├── standardize.py  (截面 Z-score)
  ├── neutralize.py   (主题中性化)
  └── pipeline.py     (编排器)

Day 3: 集成 + 测试
  ├── 重构 rebuild_factors → 双输出 (raw + processed)
  └── 单元测试
```

**验收标准**:
- 7 个因子均经过处理管线，输出 `factors_processed.parquet`
- 处理后因子分布无明显异常值
- 主题中性化后，同一主题内排名分布均匀

### Phase 2: Factor Evaluation Engine（预计 4-5 天）

**目标**: 能回答"这个因子好不好"的完整评估系统

```
Day 4-5: evaluation/ 核心逻辑
  ├── ic_analysis.py     (Rank IC + t-stat)
  ├── ic_decay.py        (多前瞻周期 IC)
  └── quantile_analysis.py (分位数收益)

Day 6-7: evaluation/ 辅助 + 报告
  ├── correlation.py     (相关性矩阵)
  ├── turnover.py        (排名自相关, 迁移矩阵)
  ├── report.py          (生成 FactorEvaluationReport)
  └── evaluation_service.py

Day 8: API + 前端对接
  ├── api/v1/evaluation.py
  └── 前端 FactorEvaluationCard + ICChart 组件
```

**验收标准**:
- `GET /api/evaluation/momentum_60d/report` 返回完整 IC 统计
- Rank IC 均值、ICIR、t-stat 可读
- 分位数收益单调性被标记
- 因子相关性矩阵展示冗余关系

### Phase 3: Signal Synthesis（预计 2-3 天）

**目标**: 基于评估结果的有依据的因子合成

```
Day 9-10: synthesis/
  ├── selection.py    (自动筛选有效因子)
  ├── weighting.py    (ICIR 加权 + 相关惩罚)
  ├── combination.py  (多因子合成)
  └── signal_service.py (重构)

Day 11: 前端
  └── SignalCompositionPanel (展示权重来源和贡献)
```

**验收标准**:
- ICIR 权重自动计算，高 IC 因子权重大
- 相关性 > 0.7 的因子对被标记并惩罚
- 综合信号得分可分解到各因子贡献

### Phase 4: Backtest + Attribution（预计 2-3 天）

**目标**: 消除前视偏差 + 收益来源可归因

```
Day 12-13: backtest/
  ├── universe.py    (时点敏感池)
  ├── attribution.py (因子回归归因)
  └── backtest_service.py (重构)

Day 14: 前端
  └── AttributionPanel (收益归因拆解)
```

### Phase 5: Monitoring + Polish（预计 1-2 天）

```
Day 15-16:
  ├── monitoring/    (因子健康检查)
  ├── 清理硬编码样本数据
  ├── 重构 _records() 去重
  ├── 修复 GET 副作用
  └── 文档更新 (CLAUDE.md)
```

### 总时间线

```
Phase 1  ████████░░░░░░░░░░░░  2-3 天
Phase 2  ████████████░░░░░░░░  4-5 天  ← 最核心
Phase 3  ██████░░░░░░░░░░░░░░  2-3 天
Phase 4  ██████░░░░░░░░░░░░░░  2-3 天
Phase 5  ████░░░░░░░░░░░░░░░░  1-2 天
         ─────────────────────
         总计: 11-16 天
```

---

## 八、从蓝图到实用：缺失的关键环节

前面的设计解决的是"因子研究的方法论问题"——如何计算、处理、评估、合成因子。但作为个人投资者，你真正需要的不是一套方法论，而是一个**能辅助你做投资决策的工具**。

这一节回答：蓝图和"能用"之间还差什么。

### 8.1 你实际的使用场景是什么？

作为个人投资者使用这个工具，你的日常应该是这样的：

```
┌─────────────────────────────────────────────────────────────────┐
│                   个人投资研究决策循环                            │
│                                                                  │
│   ┌──────────────────┐                                          │
│   │ 1. 发现/验证因子  │  ← "这个指标有没有用？"                    │
│   │   快速试一个想法   │     "20日动量和60日动量哪个更好？"         │
│   └────────┬─────────┘                                          │
│            │                                                     │
│            ▼                                                     │
│   ┌──────────────────┐                                          │
│   │ 2. 筛选标的      │  ← "当前哪些 ETF 值得关注？"               │
│   │   信号排名 + 过滤  │     "为什么是这几只而不是那几只？"         │
│   └────────┬─────────┘                                          │
│            │                                                     │
│            ▼                                                     │
│   ┌──────────────────┐                                          │
│   │ 3. 验证策略      │  ← "如果按这个规则买，历史表现如何？"        │
│   │   回测 + 样本外    │     "最近表现好是因为因子有效还是运气？"     │
│   └────────┬─────────┘                                          │
│            │                                                     │
│            ▼                                                     │
│   ┌──────────────────┐                                          │
│   │ 4. 跟踪决策      │  ← "上个月关注的 ETF 后来怎么样了？"        │
│   │   记录 + 复盘      │     "信号有没有失效的趋势？"               │
│   └──────────────────┘                                          │
└─────────────────────────────────────────────────────────────────┘
```

**当前蓝图覆盖了步骤 1（部分）和步骤 3（部分），但步骤 2（筛选标的）和步骤 4（跟踪决策）几乎完全缺失。**

### 8.2 对比：业界真实可用的系统做了什么

| 能力 | Wind 终端 | QuantConnect | Bloomberg | 当前蓝图 | 差距 |
|------|----------|-------------|-----------|---------|------|
| 数据采集 | ✅ 全自动 | ✅ 多源 | ✅ 实时 | ⚠️ 手动触发 | **缺自动化** |
| 因子计算 | ✅ 内置300+ | ✅ 自定义 | ✅ 内置+自定义 | ✅ 自定义7个 | 够用 |
| 因子评估 | ✅ IC/ICIR/分组 | ✅ Alphalens集成 | ✅ 归因报告 | ✅ Phase 2 | 设计合理 |
| **因子对比** | ✅ A vs B | ✅ 多因子对比 | ✅ | ❌ | **缺** |
| **参数扫描** | ✅ | ✅ | ✅ | ❌ | **缺** |
| **Walk-forward** | ✅ | ✅ | ✅ | ❌ | **★ 最关键的缺失** |
| 回测 | ✅ 完善 | ✅ 完善 | ✅ 完善 | △ 基础 | 够用 |
| **样本外验证** | ✅ 滚动窗口 | ✅ | ✅ | ❌ | **★ 缺** |
| **信号跟踪** | ✅ | ✅ | ⚠️ | ❌ | **缺** |
| **决策日志** | ⚠️ 非核心 | ⚠️ | ⚠️ | ❌ | 可后补 |
| 组合优化 | ✅ | ✅ | ✅ | ❌ | 可后补 |
| 实时预警 | ✅ | ✅ | ✅ | ❌ | 可后补 |
| 移动端 | ✅ | ⚠️ | ✅ | ❌ | 不需要 |

### 8.3 ★ 最关键的缺失：Walk-forward 验证框架

#### 8.3.1 为什么 Walk-forward 是必需的

当前蓝图中的评估和回测都在**全样本**上做——你用 2023-2026 的全部数据来计算 IC 和回测收益。这带来了一个致命问题：**in-sample overfitting（样本内过拟合）**。

具体来说：
- IC 统计告诉你"动量因子在 2023-2026 年表现好"——但这是**事后诸葛亮**
- 回测告诉你"这个策略 3 年赚了 X%"——但你已经**用了全部未来信息来调参**
- 如果你根据全样本 ICIR 来决定权重，然后回测验证——你在**用同一个数据做训练和测试**

真正的量化研究员的做法是 **Walk-forward（滚动窗口）**：

```
时间轴 →
├───────┬───────┬───────┬───────┬───────┬───────┤
│ Train │ Test  │       │       │       │       │  Window 1
│       ├───────┼───────┼───────┤       │       │
│       │ Train │ Test  │       │       │       │  Window 2
│       │       ├───────┼───────┼───────┤       │
│       │       │ Train │ Test  │       │       │  Window 3
│       │       │       ├───────┼───────┼───────┤
│       │       │       │ Train │ Test  │       │  Window 4
└───────┴───────┴───────┴───────┴───────┴───────┘
        ↑ Training window (e.g., 24 months)
                        ↑ Testing window (e.g., 6 months)
                            ↑ Step forward by testing window
```

每个窗口：
1. **Training**: 用过去 24 个月的数据 → 计算 IC → 筛选因子 → 确定权重
2. **Testing**: 用确定的权重 → 在接下来 6 个月上做**纯样本外**验证
3. **滑动**: 窗口前移 6 个月，重复

最终评估的是**所有测试窗口的拼接表现**，而非全样本的一次性拟合。

#### 8.3.2 Walk-forward 的模块设计

```python
# backtest/walk_forward.py

@dataclass
class WalkForwardConfig:
    train_months: int = 24        # 训练窗口长度
    test_months: int = 6          # 测试窗口长度
    step_months: int = 6          # 滑动步长
    min_train_samples: int = 12   # 最少训练样本数
    rebalance: str = "monthly"


@dataclass
class WalkForwardWindow:
    """单个滚动窗口的结果"""
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    # 训练阶段
    selected_factors: list[str]
    factor_weights: dict[str, float]
    train_icir: dict[str, float]
    # 测试阶段（纯样本外）
    test_metrics: BacktestMetrics
    test_equity_curve: list[BacktestEquityPoint]
    # 诊断
    is_factor_stable: bool          # 训练阶段选中的因子在测试阶段是否仍有效


@dataclass
class WalkForwardResult:
    """Walk-forward 总体结果"""
    config: WalkForwardConfig
    windows: list[WalkForwardWindow]
    
    # ★ 核心: 拼接的样本外净值曲线（所有 test 窗口拼接）
    oos_equity_curve: list[BacktestEquityPoint]
    oos_metrics: BacktestMetrics
    
    # ★ 关键: IS/OOS 差距
    is_metrics: BacktestMetrics      # 全样本内回测（对比用）
    oos_is_spread: float             # OOS年化 - IS年化，负值 = 过拟合
    
    # 因子稳定性
    factor_selection_stability: float  # 各窗口选中因子的 Jaccard 相似度
    weight_stability: dict[str, float] # 每个因子权重的跨窗口变异系数
    
    # 结论
    overfit_warning: str            # "严重过拟合" / "轻微过拟合" / "样本内外一致"
    verdict: str                    # "策略可靠" / "需要更多验证" / "不可用"


def run_walk_forward(
    daily_data: pd.DataFrame,
    processed_factors: pd.DataFrame,
    config: WalkForwardConfig = WalkForwardConfig(),
) -> WalkForwardResult:
    """
    ★ 核心函数: 滚动窗口验证。
    
    这是整个系统最重要的评估——它回答的是：
    "如果我严格只用在过去学到的规则，未来真的能赚钱吗？"
    而非
    "如果我知道所有历史数据，可以拼出多好看的曲线？"
    """
```

#### 8.3.3 Walk-forward 告诉你的关键信息

| 指标 | 含义 | 好策略的标准 |
|------|------|-------------|
| **OOS/IS Spread** | 样本外收益 - 样本内收益 | > -3%（差距越小越好） |
| **Factor Stability** | 各窗口选中相同的因子吗？ | Jaccard > 0.6 |
| **Weight Stability** | 各窗口给同一因子的权重稳定吗？ | CV < 0.5 |
| **OOS Win Rate** | 样本外窗口正收益的比例 | > 60% |
| **Max OOS Drawdown** | 样本外最大回撤 | 小于 IS 最大回撤的 1.5 倍 |

**如果 OOS/IS spread 是 -15%**（样本内年化 20%，样本外只有 5%），说明策略严重过拟合——你只是在拟合噪声。

### 8.4 缺失环节二：参数扫描与因子对比

目前蓝图设计的是"计算 7 个固定参数的因子 → 评估 → 合成"。但实际研究中你会不断问：

> "动量用 20 日、60 日、还是 120 日？哪个效果好？"
> "波动率用 30 日还是 60 日滚动窗口？"
> "成交额过滤用 Top-50 还是 Top-100？"

这些问题的答案**不可能事前知道**——需要通过参数扫描来回答。而且这个答案**会随时间变化**。

```python
# evaluation/parameter_scan.py

@dataclass
class ParameterScan:
    """因子参数扫描"""
    factor_base: str               # e.g., "momentum"
    parameter: str                 # e.g., "lookback_days"
    values: list[int]              # e.g., [20, 40, 60, 120]
    results: dict[int, FactorICStats]  # 每个参数值的 IC 统计
    best_value: int                # 最佳参数
    best_icir: float
    ic_decay_by_param: dict[int, dict[int, float]]  # 每个参数的 IC 衰减
    stability_note: str            # "参数在 40-60 之间表现稳定，60 最优"


def scan_parameter(
    factor_class: type[Factor],
    param_name: str,
    param_values: list,
    daily_data: pd.DataFrame,
) -> ParameterScan:
    """
    对因子的某个参数做扫描，比较不同参数值的 ICIR。
    这比硬编码 lookback_days=60 更有说服力——你知道 60 是选出来的，不是拍出来的。
    """
```

**但注意**：参数扫描必须嵌入 Walk-forward 框架中——在每个训练窗口内独立做参数选择，而不是在全样本上选最优参数。否则你还是在 overfit。

```
正确做法:
  Window 1: Train(2023) → 扫描参数, 选 best → Test(2024H1) 用 best 参数
  Window 2: Train(2023H2-2024H1) → 重新扫描, 可能选不同参数 → Test(2024H2)
  ...

错误做法:
  Full Sample(2023-2026) → 扫描参数, 选 best → 回测用 best 参数
  ↑ 这就是前视偏差——你在用未来信息选参数
```

### 8.5 缺失环节三：决策支持层

当前蓝图把信号合成当做终点（输出 research_score + 排名）。但对个人投资者来说，排名只是一个输入，你需要的是**可操作的决策支持**：

```
当前输出:                      你实际需要的:
                                
ETF ranking by score            ✓ 哪些 ETF 当前得分高？
                                ✗ 为什么得分高？（哪个因子贡献最大？）
                                ✗ 这个得分和上个月比变化大吗？
                                ✗ 这个 ETF 历史上得分一直高吗？还是突然跳上来的？
                                ✗ 得分高的 ETF 集中在某个主题吗？（偏配风险）
                                ✗ 当前信号的 confidence 如何？（IC 在衰减吗？）
                                ✗ 我应该关注多少只？（分散化 vs 集中度）
```

决策支持层在 `synthesis/` 之上的薄封装：

```python
# services/decision_service.py

class DecisionSupport:
    """为个人投资者提供决策辅助信息"""
    
    def current_top_picks(self, n: int = 10) -> list[TopPick]:
        """当前 Top-N ETF + 为什么"""
        # 每只 ETF 附带: 分数、主要驱动因子、分数变化趋势
        
    def signal_health_check(self) -> SignalHealth:
        """当前信号是否健康？"""
        # - 因子 IC 是否在衰减？
        # - 是否有因子突然失效？
        # - 综合信号和未来收益的近期相关性
        
    def concentration_warning(self) -> ConcentrationCheck:
        """偏配风险检查"""
        # - Top-10 有多少集中在某个主题？
        # - 相对于等权配置，主题偏配多大？
        
    def change_log(self, lookback_days: int = 30) -> list[SignalChange]:
        """最近变化的总结"""
        # - 哪些 ETF 新进入 Top-20？
        # - 哪些 ETF 掉出了 Top-20？
        # - 综合信号整体是变强了还是变弱了？
```

### 8.6 缺失环节四：信号跟踪与复盘

你上个月根据信号关注了 5 只 ETF。一个月后，你应该能回答：

- 这 5 只 ETF 后来表现如何？（收益 vs 基准）
- 信号判断对吗？（高分的真的涨了吗？低分的真的跌了吗？）
- 回测中的表现和实际表现一致吗？

这是研究闭环——没有这个环节，你永远不知道你的系统在实战中到底有没有用。

```python
# monitoring/signal_tracker.py

class SignalTracker:
    """跟踪历史信号的实际表现"""
    
    def track_signal(self, date: date, top_n: int = 10):
        """记录当天的信号快照"""
        # 存为 signal_snapshots.parquet
        
    def evaluate_past_signals(self, horizon_days: int = 20) -> SignalPerformance:
        """
        回头看: 过去发出的信号，horizon 天后表现如何？
        
        回答:
        - "Top-10 信号在 20 个交易日后的平均收益是多少？"
        - "和随机选 10 只 ETF 比，超额收益是多少？"
        - "信号的正判率（高分 ETF 跑赢基准的比例）是多少？"
        """
```

### 8.7 差距总结

```
业界完整研究体系:                    当前蓝图覆盖:          还需补的:

Universe (时点池)                    ✅ 设计完成            -
Alpha (因子计算)                     ✅ 设计完成            -
Processing (去极值/标准化/中性化)      ✅ 设计完成            -
Evaluation (IC/ICIR/分组)            ✅ 设计完成            -
★ Parameter Scan (参数选择)          ❌ 完全缺失            Phase 2.5
★ Factor Comparison (因子对比)        ❌ 完全缺失            Phase 2.5
★ Walk-forward (样本外验证)           ❌ ★ 最关键的缺失      Phase 3.5
Synthesis (信号合成)                  ✅ 设计完成            -
★ Decision Support (决策辅助)         ❌ 完全缺失            Phase 4.5
Portfolio (组合构建)                  △ 仅有等权            -
★ Signal Tracking (信号跟踪复盘)      ❌ 完全缺失            Phase 5
Attribution (归因)                    ✅ 设计完成            -
Monitoring (监控)                     ✅ 设计完成            -
```

---

## 九、修正后的实施路线图

### 9.1 新的 Phase 划分

考虑到 Walk-forward 的重要性和缺失环节，重新编排实施优先级：

```
Phase 1: Factor Processing (3-4 天)
  └── 去极值 / 标准化 / 中性化 / 双文件存储
  └── ★ 数据可用性检查: AKShare ETF 特有数据（折溢价、跟踪误差、规模）

Phase 2: Factor Evaluation Core (5-7 天)
  └── IC / IC Decay / Quantile / Correlation (Spearman)
  └── ★ Factor Comparison: 任意两个因子的并排对比
  └── ★ Parameter Scan: 因子参数扫描（lookback 等）
  └── 前端: 评估仪表板 (IC 时序 / 衰减 / 相关性热力图 / 对比视图)

Phase 3: Walk-forward + Signal Synthesis (5-7 天)  ← ★ ★ 最核心
  └── Walk-forward 框架: 滚动窗口训练+验证
  └── 在每个窗口内: 参数扫描 → 因子筛选 → ICIR 加权 → 样本外回测
  └── OOS vs IS 对比 + 过拟合检测
  └── Signal Synthesis: 基于 Walk-forward 验证后的因子和权重
  └── 前端: Walk-forward 结果展示 + 信号合成面板

Phase 4: Backtest + Attribution (3-4 天)
  └── 时点敏感池 / 绩效归因 / 多基准对比
  └── 前端: 增强版回测面板

Phase 5: Decision Support + Signal Tracking (3-4 天)
  └── Decision Support API: Top picks + 主题集中度 + 变化日志
  └── Signal Tracker: 信号快照 + 实际表现评估
  └── 前端: 决策辅助面板 + 复盘页面

Phase 6: Polish + Hardening (2-3 天)
  └── 修复 GET 副作用 / 去重 / 清理硬编码样本数据
  └── 健康检查增强 / 文档同步
```

### 9.2 关键里程碑

| 里程碑 | 完成后你能做什么 |
|--------|-----------------|
| Phase 1 完成 | 因子值干净了，不会被异常值干扰排名 |
| Phase 2 完成 | **知道哪个因子有用、哪个是冗余的、哪个参数好** |
| Phase 3 完成 | **知道策略在样本外是否真的有效，而非过拟合的假象** |
| Phase 4 完成 | 时点正确的回测 + 收益来源归因 |
| Phase 5 完成 | **日常能用：打开页面 → 看到当前值得关注的 ETF + 为什么** |
| Phase 6 完成 | 代码干净、文档准确、可以长期维护 |

### 9.3 修正后时间线

```
Phase 1  ██████░░░░░░░░░░░░░░░░  3-4 天
Phase 2  ██████████░░░░░░░░░░░░  5-7 天  ← 核心: 知道因子好不好
Phase 3  ██████████░░░░░░░░░░░░  5-7 天  ← ★ 最核心: 知道策略能不能赚钱
Phase 4  ██████░░░░░░░░░░░░░░░░  3-4 天
Phase 5  ██████░░░░░░░░░░░░░░░░  3-4 天
Phase 6  ████░░░░░░░░░░░░░░░░░░  2-3 天
         ─────────────────────
         总计: 21-29 天 (约 4-6 周)
```

---

## 十、向后兼容性

以下现有API保持兼容，内部实现可能重构：

| API | 兼容策略 |
|-----|---------|
| `GET /api/etfs` | 完全保留 |
| `GET /api/etfs/{symbol}/daily` | 完全保留 |
| `GET /api/status` | 完全保留 |
| `POST /api/refresh/top-etfs` | 完全保留 |
| `GET /api/factors` | 保留，增加 `?processed=true` 参数 |
| `GET /api/factors/diagnostics` | 重构为返回 FactorEvaluationReport 子集 |
| `GET /api/factors/definitions` | 保留 |
| `POST /api/factors/rebuild` | 保留，新增自动触发评估 |
| `GET /api/signals` | 重构后端逻辑，API 契约保持 |
| `GET /api/backtests/research-signal` | 重构后端逻辑，API 契约保持 |

---

## 十一、关键设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 评估指标首选 | Rank IC (Spearman) | 对异常值和分布形态更稳健 |
| 去极值方法 | MAD (n=5) | ETF 数据常有厚尾，MAD 比标准差法更稳健 |
| 中性化方法 | Intra-group rank | 不依赖线性回归假设，ETF 主题间差异大概率非线性 |
| 权重方案 | ICIR 加权 + 相关性惩罚 | 同时考虑预测力和稳定性，有学术支撑 |
| 因子排除阈值 | ICIR < 0.2 或 IC t-stat < 1.5 | 保守门槛，平衡因子多样性和质量 |
| 相关性惩罚 | 对 |ρ| > 0.6 的因子对减权 | 防止重复计量同一维度 |
| 回测池 | 时点敏感的 20 日均成交额排序 | 消除前视偏差 |
| 数据存储 | 双文件: raw + processed | 处理可追溯，评估用 processed |
| **验证框架** | **Walk-forward 滚动窗口** | 样本外验证是唯一能防止过拟合的方法 |
| **参数选择** | **训练窗口内独立扫描，不做全样本选择** | 全样本选参 = 前视偏差 |
| **Train/Test 划分** | **24个月训练 / 6个月测试 / 滚动步长6月** | 平衡数据量和样本外周期数 |
| **决策支持** | **在信号之上构建薄封装层** | 排名 ≠ 决策，需要主题集中度、变化趋势等上下文 |
| **信号复盘** | **定期快照 + 事后评估** | 不跟踪就无法知道系统到底有没有用 |

---

## 十二、参考资源

### 核心论文

- Fama, E. F., & French, K. R. (1993). Common risk factors in the returns on stocks and bonds.
- Carhart, M. M. (1997). On persistence in mutual fund performance.
- Grinold, R. C., & Kahn, R. N. (2000). *Active Portfolio Management*. (IC/ICIR 的理论基础)

### 工具文档

- [Alphalens Documentation](https://github.com/stefan-jansen/alphalens-reloaded) — 因子评估的 API 设计参考
- [Pyfolio Documentation](https://github.com/quantopian/pyfolio) — 绩效归因的 tear sheet 参考
- [Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) — 组合优化的 Python 实现
- [Quantopian Lectures](https://github.com/quantopian/lectures) — 量化研究 pipeline 的教学材料
