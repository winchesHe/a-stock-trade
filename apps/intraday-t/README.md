# intraday-t

实时做 T 独立工具，规划为开盘订阅指定 A 股实时行情、本地落盘、分钟聚合、盘中信号分析与盘后复盘。

当前状态：阶段 2 分钟聚合器开发中。

设计文档：`../../docs/intraday-t-tool-design.md`

数据源规划：

- 实时行情：百度财经 WebSocket。
- 通达信数据：主用 `easy_tdx`，`mootdx` fallback。
- 盘前候选：同花顺问财 + `a-stock-data`。

边界：

- 不做自动交易。
- 做 T 必须基于已有底仓。
- 第一版只做实时采集与解释型信号。

## 快速开始

安装开发包：

```bash
python -m pip install -e apps/intraday-t
```

采集多只股票的第一条有效快照并退出：

```bash
python apps/intraday-t/scripts/intraday_collector.py \
  --codes 002463,600941,603986 \
  --once
```

持续采集：

```bash
python apps/intraday-t/scripts/intraday_collector.py \
  --codes 002463,600941,603986
```

原始快照默认写入：

```text
apps/intraday-t/data/intraday/<交易日>/raw/<股票代码>.jsonl
```

`--once` 不是只支持单只股票，而是每只订阅股票收到第一条有效快照后退出。

生成 1 分钟聚合数据：

```bash
python apps/intraday-t/scripts/intraday_aggregator.py \
  --codes 002463,600941 \
  --day 2026-06-05
```

分钟聚合默认写入：

```text
apps/intraday-t/data/intraday/<交易日>/minute/<股票代码>_1m.jsonl
```
