# A-Stock-Trade

A 股量化投研 Monorepo —— 多应用投研工具 + AI 数据 Skill 集。

## 项目结构

```
.
├── apps/                   # 独立应用目录
│   ├── TradingAgents-astock/  # A 股多 Agent 投研框架（7 个 Analyst 角色 + 辩论决策）
│   └── intraday-t/            # 实时做 T 工具（规划中：百度 WS + easy_tdx）
├── docs/                   # 仓库级中文设计与数据源文档
├── output/                 # 产业链等输出产物
├── skills/                 # AI 编程助手用的 Skill 工具集
│   ├── a-stock-data/       # A 股全栈数据工具包（27 端点 · 13 数据源）
│   ├── dongfangcaifu-skills/  # 东方财富数据 Skill
│   ├── tonghuashun-skills/    # 同花顺数据 Skill
│   └── twitter-user-posts/    # Twitter 用户帖子抓取 Skill
└── .gitignore
```

## 快速开始

### TradingAgents-astock（A 股多 Agent 投研框架）

```bash
cd apps/TradingAgents-astock
cp .env.example .env       # 填入 API Key
make install               # 安装依赖
make web                   # 启动 Web UI
make cli                   # 或用 CLI 交互模式
```

更多命令见 `make help`。

### intraday-t（实时做 T 工具，规划中）

实时做 T 工具是独立应用，计划放在 `apps/intraday-t/`，不混入 `apps/TradingAgents-astock/`。

设计文档：`docs/intraday-t-tool-design.md`

目标能力：

- 开盘订阅指定股票实时行情。
- 本地落盘 JSONL。
- 生成分钟级聚合。
- 输出“高抛 / 低吸 / 回补 / 观望 / 禁止交易”解释型信号。
- 盘后复盘日内做 T 信号表现。

### Skills

`skills/` 下的工具集通过软链接引入，供 Claude Code 等 AI 编程助手直接调用，无需额外安装。

## 技术栈

- **框架**: LangGraph + LangChain
- **数据源**: easy_tdx / mootdx fallback / 百度财经 WebSocket / 东方财富 / 腾讯财经 / 新浪财经 / 同花顺 / 百度股市通
- **模型**: 支持 OpenAI / Anthropic / DeepSeek / Google Gemini / 通义千问等
- **UI**: Streamlit Web + Typer CLI

## 相关链接

- [TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock) — 主项目仓库
- [a-stock-data](https://github.com/simonlin1212/a-stock-data) — A 股数据 Skill
- [TradingAgents 上游](https://github.com/TauricResearch/TradingAgents) — 原版框架
