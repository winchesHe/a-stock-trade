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

## A 股数据源优先级

本仓库采用多源组合，不把所有数据都压到一个接口上。通达信基础行情、腾讯实时估值、东财独有事件数据各司其职。

| 数据源 | 优先级 | 适合做什么 | 不适合做什么 |
|---|---|---|---|
| `easy_tdx` | 通达信主源，新功能优先 | K 线、分钟线、实时报价、逐笔成交、板块排行/成分/汇总、个股资金流、集合竞价、市场异动、内置技术指标（`MACD`、`KDJ`、`RSI`、`BOLL`、`BIAS_SIGNAL`、`ZHUOYAO` 等） | PE/PB/市值/涨跌停价等估值字段 |
| `mootdx` | 通达信兜底源，兼容现有应用 | 历史 K 线、分钟线、基础报价、股票池、F10、财务文件、本地通达信离线数据 | 新战法/盘中工具的首选主源；PE/PB/市值/涨跌停价 |
| 腾讯财经 | 实时估值补充 | 实时价、涨跌幅、成交额、换手率、量比、PE/PB、市值、涨跌停价 | K 线、F10、研报、龙虎榜等深度数据 |
| 百度财经 WebSocket | 盘中实时快照 | `apps/intraday-t/` 的实时订阅与日内做 T 快照 | 历史 K 线和基本面 |
| 东方财富 | 独有事件/资金/资讯补充 | 龙虎榜、限售解禁、东财资金流、公告、研报、新闻、行业板块等 | 可由通达信/腾讯稳定取得的基础行情；批量高频请求 |

### `easy_tdx` 与 `mootdx` 怎么选

- 新开发的通达信行情能力优先接 `easy_tdx`，尤其是战法筛选、盘中监控、板块联动、集合竞价、市场异动、技术指标计算。
- 已在 `apps/TradingAgents-astock/tradingagents/dataflows/a_stock.py` 中接好的能力继续保留 `mootdx`，除非任务明确要求迁移。
- 统一适配器建议采用：`easy_tdx` 主源 → `mootdx` 兜底 → 新浪/腾讯等 HTTP 兜底。
- 当 `easy_tdx` 未安装、连接失败、字段缺失或具体命令不可用时，降级到 `mootdx`。
- 东财接口只查它独有的数据，并遵守串行限流；不要用东财批量替代通达信基础行情。

### 通达信源验证命令

```bash
cd apps/TradingAgents-astock
python -m pip install easy-tdx==1.5.0

easy-tdx kline SZ 002475 --count 5 --table
easy-tdx quote "SZ 002475" --table
easy-tdx indicator MACD -m SZ -c 002475 --count 5 --table
easy-tdx board-ranking --type HY --top 10 --table
easy-tdx belong-board SZ 002475 --table
easy-tdx capital-flow SZ 002475 --table
```

注意：`easy-tdx ping` 会并发测速多个通达信服务器，遇到单个服务器主动断连时可能抛错；验证数据源是否可用时，优先跑具体的 `kline`、`quote`、`indicator` 命令。

## 技术栈

- **框架**: LangGraph + LangChain
- **数据源**: `easy_tdx` 主通达信源 / `mootdx` 兜底 / 百度财经 WebSocket / 腾讯财经 / 东方财富 / 新浪财经 / 同花顺 / 百度股市通
- **模型**: 支持 OpenAI / Anthropic / DeepSeek / Google Gemini / 通义千问等
- **UI**: Streamlit Web + Typer CLI

## 相关链接

- [TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock) — 主项目仓库
- [a-stock-data](https://github.com/simonlin1212/a-stock-data) — A 股数据 Skill
- [TradingAgents 上游](https://github.com/TauricResearch/TradingAgents) — 原版框架
