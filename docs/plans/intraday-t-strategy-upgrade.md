# intraday-t-strategy-upgrade — Plan

> 实现节奏 + 关键设计。完成后由 `flow-ship` 归档到 `docs/plans/done/`。
> spec：`docs/specs/intraday-t-strategy-upgrade.md`

## 目标

对应 spec `§ 后续实现顺序`，把 `apps/intraday-t` 的信号引擎升级为可验证的“持仓/T 仓状态机 + 日内状态分类 + 结构策略确认”链路，同时保持现有 CLI 和 JSONL 输出兼容。

## 最小可验证链路

```bash
cd apps/intraday-t
python -m pytest tests/test_signals.py tests/test_monitor.py -v
python -m pytest tests/ -v
```

期望行为：

```text
状态机、日内分类、VWAP 回踩、二次冲高不过、二次下探不破测试通过；
monitor 仍能聚合 raw 并输出最新信号。
```

## 关键设计

- **行为**：先做风控门禁，再基于持仓状态决定可做动作，随后识别日内场景，最后匹配结构策略。
- **处理流程**：分钟 bar 输入后，先检查无底仓/时段/数据完整性/开盘风险；通过后构造持仓状态；再读取最近若干分钟走势形成日内分类；最后按优先级输出结构策略或观察/持有。
- **状态机 / 状态转移**：无底仓永远禁止；可卖底仓可开正 T 或倒 T；已高抛状态只寻找回补；已低吸状态只寻找卖出已有底仓。
- **命令链 / pipeline**：`intraday_collector` 写 raw，`aggregate_code` 生成 minute，`generate_signals_for_code` 写 signals，`monitor` 打印最新信号。
- **业务输入输出**：输入为分钟价格、VWAP、成交额增量、日内高低点、开盘/昨收偏离；输出为 signal、strategy、regime、position_state、reasons、stop_condition。
- **模块间调用关系**：`monitor/live` 调 `generate_signals_for_code`，`generate_signals_for_code` 调新版 `evaluate_bars`，`evaluate_bars` 串联风控、状态、分类、策略。

## Chunk 划分

### Chunk 1: 测试骨架与模型兼容

| # | 步 | 观察点 | 验证方式 | 状态 | reviewed |
|---|---|---|---|---|---|
| 1.1 | 写状态机与新字段失败测试 | `test_signals.py` 中出现状态字段断言 | `python -m pytest tests/test_signals.py -v` 先失败在缺少模型/函数 | ✅ | 2026-06-16 |
| 1.2 | 扩展模型并保持旧构造兼容 | 旧 `Signal(...)` 测试不需要新增参数 | `python -m pytest tests/test_signals.py -v` 至少旧用例可过 | ✅ | 2026-06-16 |

**Observability Checkpoint**：

- **运行命令**：`cd apps/intraday-t && python -m pytest tests/test_signals.py -v`
- **期望输出关键字**：状态机相关用例从缺少符号变为通过
- **失败常见根因**：dataclass 新字段没有默认值；导入名未暴露；旧测试构造 `Signal` 失败

### Chunk 2: 日内分类器

| # | 步 | 观察点 | 验证方式 | 状态 | reviewed |
|---|---|---|---|---|---|
| 2.1 | 写日内分类器失败测试 | 构造强趋势、弱趋势、震荡、开盘失败样本 | `python -m pytest tests/test_signals.py -v` 分类器用例先失败 | ✅ | 2026-06-16 |
| 2.2 | 实现分类器 | `IntradayContext.regime` 和 reasons 可读 | `python -m pytest tests/test_signals.py -v` 分类器用例通过 | ✅ | 2026-06-16 |

**Observability Checkpoint**：

- **运行命令**：`cd apps/intraday-t && python -m pytest tests/test_signals.py -v`
- **期望输出关键字**：分类器测试全部通过
- **失败常见根因**：样本分钟数不足；开盘区间切片不稳定；VWAP 缺失时没有降级

### Chunk 3: 结构策略接入

| # | 步 | 观察点 | 验证方式 | 状态 | reviewed |
|---|---|---|---|---|---|
| 3.1 | 写三类结构策略失败测试 | 测试断言 strategy/regime/action/reasons | `python -m pytest tests/test_signals.py -v` 策略用例先失败 | ✅ | 2026-06-16 |
| 3.2 | 实现策略优先级并接入 `evaluate_bars` | JSONL 信号包含 `strategy/regime/position_state` | `python -m pytest tests/test_signals.py -v` 策略和写文件用例通过 | ✅ | 2026-06-16 |
| 3.3 | 验证 monitor/live 兼容 | 终端格式可显示新增策略名或保持旧格式正常 | `python -m pytest tests/test_monitor.py tests/test_live.py -v` | ✅ | 2026-06-16 |

**Observability Checkpoint**：

- **运行命令**：`cd apps/intraday-t && python -m pytest tests/test_signals.py tests/test_monitor.py tests/test_live.py -v`
- **期望输出关键字**：三类结构策略和 monitor/live 测试通过
- **失败常见根因**：`evaluate_bars` 与旧 `evaluate_bar` 行为冲突；格式化函数没处理新增字段；测试样本没有满足策略确认条件

### Chunk 4: 文档与全量验证

| # | 步 | 观察点 | 验证方式 | 状态 | reviewed |
|---|---|---|---|---|---|
| 4.1 | 更新 README 信号逻辑说明 | README 区分新版结构策略与非目标 | `rg "结构策略|状态机|日内状态" README.md` | ✅ | 2026-06-16 |
| 4.2 | 运行 intraday-t 全量测试 | 所有 intraday-t 测试通过 | `cd apps/intraday-t && python -m pytest tests/ -v` | ✅ | 2026-06-16 |
| 4.3 | 同步 `memory/process.md`（如存在） | 存在则有本次上下文记录，不存在则说明 | `find . -path '*memory/process.md'` | ✅ | 2026-06-16 |

**Observability Checkpoint**：

- **运行命令**：`cd apps/intraday-t && python -m pytest tests/ -v`
- **期望输出关键字**：全部测试 passed
- **失败常见根因**：新增字段 JSON 序列化不兼容；旧固定阈值用例与新版路径冲突；README 文档漏改

## 风险点 + 兜底

- 结构策略启发式过拟合测试样本 —— 用偏保守阈值，条件不足输出 `watch/hold`。
- 新状态机对 CLI 暴露不足 —— 本轮先保持内部模型和测试，后续再接持仓 JSON。
- 旧单 bar API 与新版多 bar 策略语义不一致 —— 保留 `evaluate_bar` 的兼容阈值行为，多 bar 走新版结构策略。

## 验收

完成后必证：

```bash
cd apps/intraday-t
python -m pytest tests/ -v
```

必须证明：

1. 旧采集、聚合、信号、monitor、live 测试不回退。
2. 状态机、日内分类器、三类结构策略有明确单测。
3. 信号 JSONL 新增字段可序列化。
4. 文档说明当前能力和非目标。

## 非目标

本 plan 不做持仓 JSON 文件、不接券商、不做全市场扫描、不新增外部行情源、不做收益回测。

## 决策记录（活更新，Y-only）
