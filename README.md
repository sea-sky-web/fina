# Fina ETF Research

一个面向中国大陆沪深交易所可交易 ETF 的行业/主题轮动雷达。

当前核心目标是搭建一个行业/主题 ETF 轮动雷达：

- 采集 ETF 基础信息、日线行情和成交额
- 结合可人工维护的行业景气、估值分位和结构评分
- 补充 IOPV、折价率、份额、市值和 endpoint 等真实数据溯源字段
- 审计 provider、manifest、source endpoint、数据新鲜度和缓存 fallback
- 计算动量、相对强弱、流动性、风险和综合评分
- 输出观察池、可配置/重点跟踪池、回避/控仓池
- 基于已有持仓输出新增配置、加仓、减仓、持有不变的研究建议
- 提供后端 API 与 CLI
- 通过 GitHub Actions 每日生成完整报告并创建 GitHub Issue 通知

当前阶段不做：

- 实盘交易或自动下单
- 自动新闻/NLP 景气判断
- 全量成分股穿透分析
- 高频交易

## 技术栈

- 数据采集：Python, AKShare
- 存储：Parquet + DuckDB
- 后端：FastAPI
- 研究任务：后端 CLI job
- 自动化：GitHub Actions + GitHub Issue 通知

## 目录

```text
backend/          FastAPI 后端与数据采集任务
config/           人工维护的行业景气、估值和结构评分输入
data/             本地数据目录, 默认不提交真实数据
docs/             架构、约束、数据约定
scripts/          项目级辅助脚本
```

核心文档：

- [Architecture](docs/ARCHITECTURE.md)
- [Research Flow](docs/RESEARCH_FLOW.md)
- [Project Constraints](docs/CONSTRAINTS.md)
- [Data Contract](docs/DATA_CONTRACT.md)
- [Rotation Radar Design](docs/ROTATION_RADAR_DESIGN.md)
- [Goals and Task Priorities](docs/GOALS_AND_TASKS.md)
- [Rotation Engine Risk Review (2026-07)](docs/rotation_engine_risk_review_2026-07.md)

## 快速开始

后端：

```bash
python3.11 -m venv backend/.venv
source backend/.venv/bin/activate
pip install "./backend[dev]"
PYTHONPATH=backend uvicorn app.main:app --reload
```

采集 Top 100 高流动性 ETF 数据：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.jobs.collect_top_etfs --limit 100 --lookback-days 365
```

生成每日轮动雷达报告：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.jobs.daily_signal \
  --limit 100 \
  --lookback-days 365 \
  --top-n 10 \
  --output-md artifacts/daily-signal.md \
  --output-json artifacts/daily-signal.json
```

如需把已有持仓纳入报告，可提供 `symbol,weight` CSV；`weight` 使用组合小数，
例如 `0.30` 表示 30%：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.jobs.daily_signal \
  --limit 100 \
  --lookback-days 365 \
  --top-n 10 \
  --holdings-file config/current_holdings.csv \
  --portfolio-target-count 5 \
  --output-md artifacts/daily-signal.md \
  --output-json artifacts/daily-signal.json
```

估值、结构质量和可选景气修正输入维护在：

```text
config/etf_rotation_inputs.csv
```

轮动雷达只比较行业/主题 ETF。景气分默认由同主题市场数据生成，缺失的估值和结构质量按中性分处理，避免把未知数据当成确定结论。

后端接口：

```bash
curl "http://127.0.0.1:8000/api/rotation/report?top_n=10"
curl -X POST "http://127.0.0.1:8000/api/portfolio/advice" \
  -H "Content-Type: application/json" \
  -d '{"holdings":[{"symbol":"159998.SZ","weight":0.2}],"target_count":5}'
curl "http://127.0.0.1:8000/api/data-sources/audit"
```

## GitHub Actions

`.github/workflows/daily-signal.yml` 会在工作日北京时间 17:30 自动运行，也可以在
GitHub Actions 页面手动触发。任务会刷新 ETF 数据、生成 Top10 轮动雷达，
创建一条 GitHub Issue 作为通知，并上传 `daily-signal-report` artifact。

Issue 正文就是完整报告，包括数据刷新状态、Top10 排名、评分拆解、状态标签、
数据源真实性审计、风险提示和刷新失败明细。这个通知方式不需要额外 secret；
在 GitHub 上 watch 本仓库即可收到网页、邮件或手机 App 通知。

如果后续仍需要其他通知渠道，可以在 `backend/app/jobs/daily_signal.py` 的
Markdown 报告基础上再接对应 webhook 或邮件发送器。

## 投资风险说明

本项目只用于数据研究和学习，不构成任何投资建议。ETF 仍然存在市场风险、流动性风险、跟踪误差、折溢价、费用和数据质量风险。
