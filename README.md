# Fina ETF Research

一个面向中国大陆沪深交易所可交易 ETF 的数据采集、展示与后续因子研究项目。

初版目标很克制：

- 采集 ETF 基础信息与日线行情
- 将原始数据与清洗数据分层保存
- 提供基础 API 给前端展示
- 为后续接入 Qlib 因子分析预留标准字段与导出路径

当前阶段不做：

- 自动荐股或买卖建议
- 实盘交易
- 复杂因子分析
- 组合优化
- 高频交易

## 技术栈

- 数据采集：Python, AKShare
- 存储：Parquet + DuckDB
- 后端：FastAPI
- 前端：React + Vite + TypeScript
- 图表：自定义 SVG K 线与成交量图
- 后续研究：Qlib

## 目录

```text
backend/          FastAPI 后端与数据采集任务
frontend/         React 前端
data/             本地数据目录, 默认不提交真实数据
docs/             架构、约束、数据约定
scripts/          项目级辅助脚本
```

核心文档：

- [Architecture](docs/ARCHITECTURE.md)
- [Project Constraints](docs/CONSTRAINTS.md)
- [Data Contract](docs/DATA_CONTRACT.md)
- [Goals and Task Priorities](docs/GOALS_AND_TASKS.md)

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

生成每日研究信号摘要：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.jobs.daily_signal \
  --limit 100 \
  --lookback-days 365 \
  --top-n 10 \
  --output-md artifacts/daily-signal.md \
  --output-json artifacts/daily-signal.json
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## GitHub Actions

`.github/workflows/daily-signal.yml` 会在工作日北京时间 17:30 自动运行，也可以在
GitHub Actions 页面手动触发。任务会刷新 ETF 数据、重建因子、生成 Top10 研究信号，
发送完整飞书报告，并上传 `daily-signal-report` artifact。

如果需要飞书通知，在 GitHub 仓库的 Settings → Secrets and variables → Actions
中添加：

- `FEISHU_BOT_WEBHOOK`
- `FEISHU_BOT_SECRET`

工作流使用严格通知模式；未配置飞书 secret 或通知发送失败时，任务会失败并在日志中
显示原因，避免静默漏通知。

## 投资风险说明

本项目只用于数据研究和学习，不构成任何投资建议。ETF 仍然存在市场风险、流动性风险、跟踪误差、折溢价、费用和数据质量风险。
