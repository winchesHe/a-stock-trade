# intraday-t

实时做 T 独立工具，规划为开盘订阅指定 A 股实时行情、本地落盘、分钟聚合、盘中信号分析与盘后复盘。

当前状态：阶段 3 基础信号引擎开发中。

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

单终端实时采集并展示信号（推荐）：

```bash
python apps/intraday-t/scripts/intraday_live.py \
  --codes 002463,600941 \
  --day 2026-06-05 \
  --interval 20
```

该命令会在同一个终端里同时完成：

- 订阅百度财经 WebSocket 并写入 raw 快照；
- 定时聚合 1 分钟数据；
- 定时生成并打印最新做 T 信号。

按 `Ctrl+C` 会同时停止采集和信号展示。

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

生成基础做 T 信号：

```bash
python apps/intraday-t/scripts/intraday_signal.py \
  --codes 002463,600941 \
  --day 2026-06-05
```

无底仓时只输出禁止交易信号：

```bash
python apps/intraday-t/scripts/intraday_signal.py \
  --codes 002463 \
  --day 2026-06-05 \
  --no-position
```

信号默认写入：

```text
apps/intraday-t/data/intraday/<交易日>/signals/<股票代码>_signals.jsonl
```

终端实时观察信号：

```bash
python apps/intraday-t/scripts/intraday_monitor.py \
  --codes 002463,600941 \
  --day 2026-06-05 \
  --interval 20
```

只刷新并展示一次：

```bash
python apps/intraday-t/scripts/intraday_monitor.py \
  --codes 002463,600941 \
  --day 2026-06-05 \
  --once
```

输出示例：

```text
---- 2026-06-08 13:55:33 ----
2026-06-08T13:55:00+08:00 605589 low_buy 强度79 价50.06 / VWAP 51.05 | 低吸计划 T 仓 | 原因：价格低于 VWAP 1.93%；价格接近日内低点 | 失效：放量跌破日内低点则取消低吸信号
```

说明：`intraday_monitor.py` 不负责采集，它会循环执行“聚合 raw → 生成信号 → 打印最新信号”。使用时需要另一个终端先运行 `intraday_collector.py` 持续写入 raw 数据。

## 当前做 T 判断逻辑

当前信号引擎已从单一 VWAP 偏离阈值升级为三层判断：

1. 风控门禁：无底仓、非交易时段、缺少 VWAP、开盘后前几分钟，优先输出 `forbidden`。
2. 持仓/T 仓状态机：区分 `no_base_position`、`base_available`、`sold_waiting_cover`、`bought_waiting_sell`。其中 CLI 暂时只通过 `--no-position` 暴露无底仓，其余状态先由代码层和测试覆盖，后续可接持仓 JSON。
3. 结构策略：在日内状态分类后，优先匹配二次冲高不过高抛、二次下探不破低吸、VWAP 回踩低吸。条件不足时输出 `watch` 或 `hold`，不再只因为固定偏离率直接交易。

终端输出中的方括号会展示策略、日内状态和仓位状态，例如：

```text
2026-06-08T13:55:00+08:00 605589 low_buy [vwap_pullback_low_buy/strong_trend/base_available] 强度71 ...
```

日内状态分类包括：

- `strong_trend`：近端多数时间在 VWAP 上方，价格相对开盘或昨收偏强。
- `weak_trend`：近端多数时间在 VWAP 下方，价格相对开盘或昨收偏弱。
- `range_bound`：VWAP 上下偏离较小，结构不明确。
- `panic_reversal`：日内低点后出现修复。
- `opening_breakout`：突破开盘区间并站在 VWAP 上方。
- `opening_failed_breakout`：突破开盘区间后跌回区间或 VWAP 下方。
