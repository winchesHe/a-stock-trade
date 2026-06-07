# A-Stock-Trade Agent Rules

## 项目结构

```text
.
├── apps/
│   ├── TradingAgents-astock/  # A 股多 Agent 投研框架，含 Streamlit Web、CLI、投研链路
│   └── intraday-t/            # 实时做 T 独立工具，规划为百度 WS + easy_tdx 主源
├── docs/                      # 仓库级中文设计文档、数据源记录、实时做 T 方案
├── output/                    # 产业链 HTML/Markdown 等生成产物
├── skills/                    # AI 助手用 Skill 集，非主应用代码
├── AGENTS.md                  # 当前代理规则
└── README.md                  # 仓库说明
```

- `apps/TradingAgents-astock/` 和 `apps/intraday-t/` 是两个独立应用，不要互相混放代码。
- `docs/` 放跨应用设计和研究记录；应用内部文档可放各自应用目录。
- `skills/` 只给 AI 助手调用，除非明确维护 skill，否则不要把业务逻辑写进去。

## 工作边界

- 默认用中文回复，新增文档也用中文。
- 仓库采用 `apps/` 多应用布局：`apps/TradingAgents-astock/` 是 A 股多 Agent 投研框架；`apps/intraday-t/` 预留给实时做 T 工具。
- 根目录 `skills/` 是给 AI 助手用的数据 Skill 集，非主应用代码。
- 修改前先确认范围和验收标准；优先做最小可验证改动。
- 不要删除或重置用户已有变更；遇到无关 dirty files 只记录，不回滚。

## 常用命令

在主项目内执行：

```bash
cd apps/TradingAgents-astock
python -m pip install -e .
tradingagents-web
streamlit run web/app.py
python -m pytest tests/ -v
```

注意：`python -m pip install -e .` 会安装 `mootdx`，并可能把当前环境的 `httpx/openai/anthropic` 改到项目依赖版本；如果同一 Python 环境还跑 `browser-use`、`mcp`、`google-genai`，先建独立虚拟环境再装。

通达信主源验证（在独立虚拟环境或 `apps/TradingAgents-astock/.venv` 内执行）：

```bash
python -m pip install easy-tdx==1.5.0
easy-tdx kline SZ 002475 --count 5 --table
easy-tdx quote "SZ 002475" --table
easy-tdx indicator MACD -m SZ -c 002475 --count 5 --table
easy-tdx board-ranking --type HY --top 10 --table
```

`easy-tdx ping` 可能因单个通达信服务器断连而抛错；验证可用性时优先跑具体的 `kline` / `quote` / `indicator` 命令。

## 关键路径

- `apps/TradingAgents-astock/tradingagents/dataflows/a_stock.py`：A 股数据入口，行情/估值/新闻/龙虎榜/解禁/行业等接口。
- `apps/TradingAgents-astock/tradingagents/graph/trading_graph.py`：`TradingAgentsGraph` 多 Agent 主链路；成功后写历史 JSON。
- `apps/TradingAgents-astock/web/app.py`：Streamlit Web 主入口。
- `apps/TradingAgents-astock/web/history.py`：Web 历史记录扫描逻辑。
- `apps/TradingAgents-astock/web/components/report_viewer.py`：Web 报告详情展示。
- `apps/TradingAgents-astock/reports/`：本地 HTML/截图报告目录；Web UI 不直接读取这里。
- `apps/TradingAgents-astock/examples/cases/`：示例案例 Markdown。
- `apps/intraday-t/`：实时做 T 独立工具目录，主用百度 WebSocket + easy_tdx，mootdx 兜底。

## Web UI 数据规则

- `http://localhost:8501/` 的历史记录读取 `~/.tradingagents/logs/**/full_states_log_*.json`。
- 某只股票的历史 JSON 路径形如 `~/.tradingagents/logs/002463/TradingAgentsStrategy_logs/full_states_log_2026-06-02.json`。
- 只更新 `apps/TradingAgents-astock/reports/*.html` 不会刷新 Web UI 历史页；需要完整系统链路落盘 JSON，或明确同步对应 `full_states_log_<date>.json`。
- Web 历史排序按 JSON 文件名日期倒序；同一股票新日期写入后刷新页面即可看到新记录。

## A 股数据接口规则

- 通达信在线数据新功能优先用 `easy_tdx`：适合 K 线、分钟线、实时报价、逐笔、板块列表/成分/排行/汇总、个股资金流、集合竞价、市场异动、内置指标（如 `MACD`、`KDJ`、`RSI`、`BOLL`、`BIAS_SIGNAL`、`ZHUOYAO`）。
- `mootdx` 是当前 `apps/TradingAgents-astock` 已接入的兼容源，适合历史 K 线、分钟线、基础报价、股票池、F10、财务文件、本地通达信离线数据；新功能仅在 `easy_tdx` 未安装、连接失败、字段缺失或任务要求兼容现有 `a_stock.py` 时用作兜底。
- 业务代码不要直接散落依赖具体库；新增数据能力优先封装统一 provider：`easy_tdx` 主源 → `mootdx` 兜底 → 必要时新浪/腾讯等 HTTP 兜底。
- 腾讯财经用于实时估值/市值/换手/量比/涨跌停等补充字段；`mootdx` 不提供 PE/PB/市值/涨跌停价。
- 新增东财接口必须走 `a_stock.py` 内 `_em_get()`，不要裸 `requests.get` 访问 `eastmoney.com`。
- 东财接口串行限流；批量场景可设置 `EM_MIN_INTERVAL=1.5` 或更高。
- 东财只用于其独有数据，如龙虎榜、解禁、东财资金流、新闻、公告、研报、行业板块等；不要用东财替代可由 `easy_tdx` / `mootdx` / 腾讯稳定取得的基础行情。
- 外部源失败要在报告中标注：例如百度概念接口可能 403，东财资金流可能远端断开。

## 本地记录：沪电股份更新

- 2026-06-02 已为 `002463 沪电股份` 写入 Web 历史 JSON：`~/.tradingagents/logs/002463/TradingAgentsStrategy_logs/full_states_log_2026-06-02.json`。
- 同步生成 HTML：`apps/TradingAgents-astock/reports/002463-沪电股份-2026-06-02.html`。
- 旧 `reports/**/002463*05-30*` 已移除；Web 仍可保留旧历史 JSON `full_states_log_2026-05-30.json`，用于历史回看。
- 完整 LLM 多 Agent 链路曾启动并拉到研报/行情，但 15 分钟超时未完成；本次 06-02 Web JSON 使用项目 `a_stock` 系统数据层结果生成。

## 验收

- 代码改动：运行相关单测，至少 `python -m pytest tests/ -v` 或说明未运行原因。
- Web 历史更新：运行 `python - <<'PY'` 调用 `web.history.get_history()`，确认目标 `ticker/date/path` 出现。
- 报告更新：用 grep 验证新文件包含目标日期、股票代码、核心行情字段；确认旧日期目标文件无残留。
