# OpenClaw Use Case Daily Monitor

自动化监控 OpenClaw 在各社区平台（Reddit、GitHub、X、Discord）的 use case 讨论和 Agent 生态动态，每日生成分析报告。

## 架构

```
GitHub Actions (每日 UTC 00:00)
    ├── Reddit Scraper (API)
    ├── GitHub Scraper (API)
    ├── X Scraper (Playwright)
    └── Discord Scraper (Playwright)
            ↓
    data/raw/{date}.json
            ↓
    Processing Pipeline (去重→过滤→分类→评分)
            ↓
    data/processed/{date}.json
            ↓
    Report Generator (Claude)
            ↓
    outputs/daily-report/{date}.md + latest.md
            ↓
    OpenClaw 通过 GitHub Raw URL 获取 → 转存内部文档
```

## 快速开始

### 1. 环境准备

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置 Secrets

在 GitHub Repo Settings → Secrets 中配置：

| Secret | 说明 |
|--------|------|
| `REDDIT_CLIENT_ID` | Reddit OAuth App Client ID |
| `REDDIT_CLIENT_SECRET` | Reddit OAuth App Client Secret |
| `GH_PAT` | GitHub Personal Access Token |
| `MINIMAX_API_KEY` | MiniMax API Key (platform.minimax.io) |
| `X_COOKIES` | X/Twitter 登录 cookies (JSON) |
| `DISCORD_TOKEN` | Discord 账号 token |

### 3. 本地运行

```bash
export MINIMAX_API_KEY="your-key"
export REDDIT_CLIENT_ID="your-id"
export REDDIT_CLIENT_SECRET="your-secret"
bash scripts/run_daily.sh
```

### 4. 自动运行

Push 到 GitHub 后，GitHub Actions 会在每日 UTC 00:00（北京时间 08:00）自动执行。

也可通过 Actions 页面手动触发（workflow_dispatch）。

## 报告获取

```
# 最新报告（固定 URL）
https://raw.githubusercontent.com/{owner}/{repo}/main/outputs/daily-report/latest.md

# 按日期获取
https://raw.githubusercontent.com/{owner}/{repo}/main/outputs/daily-report/2026-03-19.md

# 报告索引
https://raw.githubusercontent.com/{owner}/{repo}/main/outputs/daily-report/index.json
```

## 关键词配置

编辑 `config/keywords.json` 即可更新监控关键词，commit 后下次运行自动生效。

## 目录结构

```
├── .github/workflows/    # GitHub Actions 定时任务
├── config/               # 关键词、平台参数、过滤规则
├── src/
│   ├── scrapers/         # 各平台抓取器
│   ├── processors/       # 去重、分类、评分
│   ├── utils/            # 通用工具（schema、LLM client、logger）
│   └── report_generator.py
├── data/raw/             # 每日原始数据
├── data/processed/       # 处理后数据
├── memory/               # 去重记忆（seen URLs）
├── prompts/              # LLM prompt 模板
├── outputs/daily-report/ # 生成的报告
└── scripts/              # 本地运行脚本
```

## 技术栈

- **Python 3.11+**
- **MiniMax M2.5** — 内容分类、评分、报告生成（通过 Anthropic 兼容 API）
- **Playwright** — X/Discord 浏览器自动化抓取
- **GitHub Actions** — 定时调度
- **Reddit API / GitHub API** — 结构化数据抓取
