# A-Stock-Trade Agent Rules

## 工作边界

- 默认用中文回复，新增文档也用中文。
- 主项目在 `TradingAgents-astock/`；根目录 `skills/` 是给 AI 助手用的数据 Skill 集，非主应用代码。
- 修改前先确认范围和验收标准；优先做最小可验证改动。
- 不要删除或重置用户已有变更；遇到无关 dirty files 只记录，不回滚。

## 常用命令

在主项目内执行：

```bash
cd TradingAgents-astock
python -m pip install -e .
tradingagents-web
streamlit run web/app.py
python -m pytest tests/ -v
```

注意：`python -m pip install -e .` 会安装 `mootdx`，并可能把当前环境的 `httpx/openai/anthropic` 改到项目依赖版本；如果同一 Python 环境还跑 `browser-use`、`mcp`、`google-genai`，先建独立虚拟环境再装。

## 关键路径

- `TradingAgents-astock/tradingagents/dataflows/a_stock.py`：A 股数据入口，行情/估值/新闻/龙虎榜/解禁/行业等接口。
- `TradingAgents-astock/tradingagents/graph/trading_graph.py`：`TradingAgentsGraph` 多 Agent 主链路；成功后写历史 JSON。
- `TradingAgents-astock/web/app.py`：Streamlit Web 主入口。
- `TradingAgents-astock/web/history.py`：Web 历史记录扫描逻辑。
- `TradingAgents-astock/web/components/report_viewer.py`：Web 报告详情展示。
- `TradingAgents-astock/reports/`：本地 HTML/截图报告目录；Web UI 不直接读取这里。
- `TradingAgents-astock/examples/cases/`：示例案例 Markdown。

## Web UI 数据规则

- `http://localhost:8501/` 的历史记录读取 `~/.tradingagents/logs/**/full_states_log_*.json`。
- 某只股票的历史 JSON 路径形如 `~/.tradingagents/logs/002463/TradingAgentsStrategy_logs/full_states_log_2026-06-02.json`。
- 只更新 `TradingAgents-astock/reports/*.html` 不会刷新 Web UI 历史页；需要完整系统链路落盘 JSON，或明确同步对应 `full_states_log_<date>.json`。
- Web 历史排序按 JSON 文件名日期倒序；同一股票新日期写入后刷新页面即可看到新记录。

## A 股数据接口规则

- 新增东财接口必须走 `a_stock.py` 内 `_em_get()`，不要裸 `requests.get` 访问 `eastmoney.com`。
- 东财接口串行限流；批量场景可设置 `EM_MIN_INTERVAL=1.5` 或更高。
- 行情/估值优先用 mootdx TCP 和腾讯财经；东财只用于其独有数据，如龙虎榜、解禁、资金流、新闻。
- 外部源失败要在报告中标注：例如百度概念接口可能 403，东财资金流可能远端断开。

## 本地记录：沪电股份更新

- 2026-06-02 已为 `002463 沪电股份` 写入 Web 历史 JSON：`~/.tradingagents/logs/002463/TradingAgentsStrategy_logs/full_states_log_2026-06-02.json`。
- 同步生成 HTML：`TradingAgents-astock/reports/002463-沪电股份-2026-06-02.html`。
- 旧 `reports/**/002463*05-30*` 已移除；Web 仍可保留旧历史 JSON `full_states_log_2026-05-30.json`，用于历史回看。
- 完整 LLM 多 Agent 链路曾启动并拉到研报/行情，但 15 分钟超时未完成；本次 06-02 Web JSON 使用项目 `a_stock` 系统数据层结果生成。

## 验收

- 代码改动：运行相关单测，至少 `python -m pytest tests/ -v` 或说明未运行原因。
- Web 历史更新：运行 `python - <<'PY'` 调用 `web.history.get_history()`，确认目标 `ticker/date/path` 出现。
- 报告更新：用 grep 验证新文件包含目标日期、股票代码、核心行情字段；确认旧日期目标文件无残留。
