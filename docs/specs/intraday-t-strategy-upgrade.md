# intraday-t-strategy-upgrade

## 概述

`apps/intraday-t/` 当前做 T 信号以固定 VWAP 偏离阈值为主，容易把趋势中的正常偏离误判为高抛/低吸。本次升级把信号引擎改为“持仓/T 仓状态机 + 日内状态分类 + 结构策略确认”的解释型辅助工具，继续保持不自动交易、不承诺收益。

核心目标：

1. 引入持仓/T 仓状态机，让信号区分无底仓、可卖底仓、已高抛待回补、已低吸待卖出等状态。
2. 引入日内状态分类器，用分钟数据识别强趋势、弱趋势、震荡、急跌修复、开盘区间突破/失败等场景。
3. 用结构策略替代单一固定阈值，优先实现 VWAP 回踩低吸、二次冲高不过高抛、二次下探不破低吸。
4. 保持现有 CLI/monitor 工作流兼容，仍输出 JSONL 信号和终端解释。

## 非目标

MVP 不做以下能力：

1. 不接券商接口，不自动下单。
2. 不做全市场扫描，不新增盘前候选池。
3. 不新增外部数据源；本次只使用现有 1 分钟 bar 字段。
4. 不做完整盘后收益回测；只保证策略信号可解释、可测试、可落盘。
5. 不承诺胜率，信号只作为人工判断参考。

## 工作区结构 / 架构

```text
apps/intraday-t/
  src/intraday_t/
    models.py       # Snapshot / MinuteBar / Signal 及新增上下文模型
    signals.py      # 风控门禁、状态机、日内分类、结构策略主入口
    monitor.py      # 聚合 raw 后生成并展示最新信号
    live.py         # 实时采集 + 信号展示
  tests/
    test_signals.py # 新增策略和状态机单测
```

数据流：

```text
raw snapshot -> 1m MinuteBar -> PositionContext -> IntradayContext -> StrategyDecision -> Signal JSONL/terminal
```

## 数据模型 / Schema

新增或扩展 Python dataclass：

```python
@dataclass(slots=True)
class PositionContext:
    has_base_position: bool = True
    base_shares: int | None = None
    planned_t_shares: int | None = None
    opened_side: str | None = None  # "sold" / "bought" / None
    opened_price: float | None = None

@dataclass(slots=True)
class IntradayContext:
    regime: str
    confidence: int
    open_range_high: float | None = None
    open_range_low: float | None = None
    recent_high: float | None = None
    recent_low: float | None = None
    reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
```

`Signal` 兼容扩展：

```python
@dataclass(slots=True)
class Signal:
    ...
    strategy: str | None = None
    regime: str | None = None
    position_state: str | None = None
```

兼容性要求：

1. 旧测试里手动构造 `Signal(...)` 不需要传新增字段。
2. JSONL 输出新增字段可以为 `null`，旧消费者可忽略。
3. `--no-position` 继续映射为 `has_base_position=False`。

## 接口设计

现有 CLI 保持可用：

```bash
python apps/intraday-t/scripts/intraday_signal.py --codes 002463 --day 2026-06-05
python apps/intraday-t/scripts/intraday_monitor.py --codes 002463 --day 2026-06-05 --once
python apps/intraday-t/scripts/intraday_live.py --codes 002463 --day 2026-06-05 --once
```

内部接口新增：

```python
def position_context_from_flags(*, has_position: bool = True) -> PositionContext: ...

def classify_intraday_context(
    bars: list[MinuteBar],
    *,
    opening_range_minutes: int = 30,
    lookback: int = 5,
) -> IntradayContext: ...

def evaluate_latest_bar(
    bars: list[MinuteBar],
    *,
    position: PositionContext,
    opening_minutes: int = 5,
) -> Signal: ...
```

兼容接口保留：

```python
def evaluate_bar(bar: MinuteBar, *, has_position: bool = True, opening_minutes: int = 5, ...) -> Signal
def evaluate_bars(bars: list[MinuteBar], *, has_position: bool = True, opening_minutes: int = 5) -> list[Signal]
```

`evaluate_bar` 作为单 bar 兼容路径，仍可输出原有阈值信号；`evaluate_bars` 和 CLI 走结构策略路径。

## 子系统设计

### 风控门禁

任何结构策略前先判断：

1. 无底仓：输出 `forbidden`。
2. 非连续竞价时段：输出 `forbidden`。
3. 缺少 VWAP / VWAP 偏离率：输出 `forbidden`。
4. 开盘后前 N 分钟：输出 `forbidden`。
5. 数据长度不足以识别结构：输出 `watch` 或 `hold`，不强行交易。

### 持仓/T 仓状态机

状态以 `PositionContext` 表达：

| 状态 | 条件 | 可输出动作 |
|---|---|---|
| `no_base_position` | `has_base_position=False` | `forbidden` |
| `base_available` | 有可卖底仓，未开 T 腿 | `high_sell` / `low_buy` / `watch` / `hold` |
| `sold_waiting_cover` | 已高抛底仓，等待低位回补 | `cover_back` / `watch` / `hold` |
| `bought_waiting_sell` | 已低吸 T 仓，等待卖出已有底仓 | `high_sell` / `watch` / `hold` |

本次 CLI 暂不新增持仓文件，先通过 `has_position` 兼容入口创建 `base_available` 或 `no_base_position`。代码层保留 `opened_side/opened_price`，后续可接持仓 JSON。

### 日内状态分类器

分类基于当前已有分钟 bar：

| regime | 判定倾向 |
|---|---|
| `strong_trend` | 多数近端 bar 在 VWAP 上方，涨幅相对昨收/开盘为正，价格接近日内高位 |
| `weak_trend` | 多数近端 bar 在 VWAP 下方，跌幅相对昨收/开盘为负，价格接近日内低位 |
| `range_bound` | VWAP 上下反复，偏离不大，未破开盘区间 |
| `panic_reversal` | 先接近日内低点，再出现修复，适合观察二探不破 |
| `opening_breakout` | 突破开盘区间高点并站在 VWAP 上方 |
| `opening_failed_breakout` | 曾突破开盘区间高点后跌回 VWAP/区间内 |

分类输出 `confidence`、`reasons` 和 `risk_flags`，供信号解释复用。

### 结构策略

策略按优先级评估：

1. 已开 T 腿闭环优先：`sold_waiting_cover` 优先找回补，`bought_waiting_sell` 优先找卖出。
2. 二次冲高不过高抛：近期先形成高点，最新价接近但未突破近期高点，量能不强，且从高位回落。
3. 二次下探不破低吸：近期先形成低点，最新价接近但未跌破近期低点，量能不强，且出现修复。
4. VWAP 回踩低吸：强势或开盘突破环境中，价格回踩 VWAP 附近未放量跌破，并重新站回 VWAP。
5. 接近条件但确认不足输出 `watch`，否则 `hold`。

## 改动范围

- `apps/intraday-t/src/intraday_t/models.py`：新增 `PositionContext`、`IntradayContext`，扩展 `Signal`。
- `apps/intraday-t/src/intraday_t/signals.py`：新增状态机、分类器、结构策略；保留兼容函数。
- `apps/intraday-t/src/intraday_t/monitor.py`：继续调用 `generate_signals_for_code`，输出新增字段无需额外处理；必要时展示策略名。
- `apps/intraday-t/README.md`：补充新版信号逻辑说明。
- `apps/intraday-t/tests/test_signals.py`：新增状态机、日内分类、结构策略单测。

## 假设

- ⚠ 百度 WebSocket 已提供的 `avg_price/amount/volume/open/pre_close` 足够支撑第一版结构策略；如部分字段缺失，策略应降级为 `watch/hold/forbidden`。
- ⚠ 第一版不读取真实持仓文件，因此 `sold_waiting_cover` / `bought_waiting_sell` 主要由代码层测试覆盖，CLI 只暴露 `--no-position`。
- ⚠ 量能判断先使用分钟 `amount_delta/volume_delta` 的近端相对变化，不引入更长历史成交基准。

## 风险

- 固定启发式仍可能对不同波动率股票不够自适应；兜底是优先输出 `watch`，并在理由中暴露触发条件。
- 分钟样本过少时容易误判二冲/二探；兜底是设置最小 bar 数，不足时不输出交易信号。
- CLI 暂无持仓文件会限制状态机实盘价值；兜底是先把内部模型和测试打通，后续接 JSON 持仓。
- 旧 JSONL 消费者若严格校验字段可能受新增字段影响；兜底是新增字段默认 `null`，保留原字段语义。

## 验收链路

运行测试：

```bash
cd apps/intraday-t
python -m pytest tests/ -v
```

必须证明：

1. 无底仓、非交易时段、数据缺失、开盘风险仍优先输出 `forbidden`。
2. `PositionContext` 能表达无底仓、可卖底仓、已高抛待回补、已低吸待卖出状态。
3. 日内分类器能识别强趋势、弱趋势、震荡、急跌修复、开盘突破/失败中的关键场景。
4. 三个结构策略分别能输出 `vwap_pullback_low_buy`、`failed_second_high_sell`、`second_low_reversal_buy` 相关信号。
5. `generate_signals_for_code` 仍能读取分钟 JSONL、写入信号 JSONL。
6. `intraday_monitor.run_once` 仍能聚合 raw、生成并格式化最新信号。

## 后续实现顺序

1. 先写状态机测试，覆盖 `--no-position` 兼容和四类状态。
2. 写日内分类器测试，构造最小分钟 bar 序列覆盖核心 regime。
3. 写三类结构策略测试，锁定信号枚举、策略名、理由和失效条件。
4. 扩展模型，加入 `PositionContext`、`IntradayContext` 和 `Signal` 新字段。
5. 实现状态机和风控门禁，保证旧 `evaluate_bar` 测试不回退。
6. 实现日内状态分类器。
7. 实现结构策略优先级，并让 `evaluate_bars/generate_signals_for_code` 走新版路径。
8. 更新 README，运行 `apps/intraday-t` 测试。
9. 查找并同步 `memory/process.md`，如不存在则在最终说明中标注。

## 参考

- 现有设计文档：`docs/intraday-t-tool-design.md`
- 当前实现：`apps/intraday-t/src/intraday_t/signals.py`
- 当前聚合：`apps/intraday-t/src/intraday_t/aggregate.py`
- 当前测试：`apps/intraday-t/tests/test_signals.py`
