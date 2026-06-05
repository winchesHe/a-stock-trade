# intraday-t

实时做 T 独立工具，规划为开盘订阅指定 A 股实时行情、本地落盘、分钟聚合、盘中信号分析与盘后复盘。

当前状态：设计阶段。

设计文档：`../../docs/intraday-t-tool-design.md`

数据源规划：

- 实时行情：百度财经 WebSocket。
- 通达信数据：主用 `easy_tdx`，`mootdx` fallback。
- 盘前候选：同花顺问财 + `a-stock-data`。

边界：

- 不做自动交易。
- 做 T 必须基于已有底仓。
- 第一版只做实时采集与解释型信号。
