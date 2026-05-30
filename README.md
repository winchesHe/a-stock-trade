# A-Stock-Trade

A 股量化投研 Monorepo —— 多 Agent 投研框架 + AI 数据工具集。

## 项目结构

```
.
├── TradingAgents-astock/   # 主项目：A 股多 Agent 投研框架（7 个 Analyst 角色 + 辩论决策）
├── skills/                 # AI 编程助手用的 Skill 工具集
│   ├── a-stock-data/       # A 股全栈数据工具包（27 端点 · 13 数据源）
│   ├── dongfangcaifu-skills/  # 东方财富数据 Skill
│   ├── tonghuashun-skills/    # 同花顺数据 Skill
│   └── twitter-user-posts/    # Twitter 用户帖子抓取 Skill
└── .gitignore
```

## 快速开始

### TradingAgents-astock（主项目）

```bash
cd TradingAgents-astock
cp .env.example .env       # 填入 API Key
make install               # 安装依赖
make web                   # 启动 Web UI
make cli                   # 或用 CLI 交互模式
```

更多命令见 `make help`。

### Skills

`skills/` 下的工具集通过软链接引入，供 Claude Code 等 AI 编程助手直接调用，无需额外安装。

## 技术栈

- **框架**: LangGraph + LangChain
- **数据源**: mootdx / 东方财富 / 腾讯财经 / 新浪财经 / 同花顺 / 财联社 / 百度股市通
- **模型**: 支持 OpenAI / Anthropic / DeepSeek / Google Gemini / 通义千问等
- **UI**: Streamlit Web + Typer CLI

## 相关链接

- [TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock) — 主项目仓库
- [a-stock-data](https://github.com/simonlin1212/a-stock-data) — A 股数据 Skill
- [TradingAgents 上游](https://github.com/TauricResearch/TradingAgents) — 原版框架
