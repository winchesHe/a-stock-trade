# intraday-t-web-ui

## 概述

`apps/intraday-t/` 已具备百度财经 WebSocket 实时采集、raw JSONL 落盘、1 分钟聚合和做 T 信号生成能力，但目前主要通过终端命令操作。本次新增本地 Web UI，让用户在浏览器里启动/停止实时采集、刷新信号、查看最新行情和信号解释。

核心目标：

1. 提供本地网页入口，支持输入股票代码、交易日、刷新间隔、底仓状态等参数。
2. 在网页中启动/停止百度 WebSocket 实时采集，并持续落盘到现有 `data/intraday/<day>/raw/`。
3. 复用现有 `aggregate_code` 和 `generate_signals_for_code`，在页面中一键刷新 1 分钟数据和做 T 信号。
4. 展示每只股票的采集状态、最新快照、最新信号、分钟线表和信号历史，仍坚持人工辅助，不做自动交易。

## 非目标

MVP 不做以下能力：

1. 不接券商接口，不自动下单，不生成真实委托。
2. 不做账号、权限、多用户或远程部署；仅作为本机 Streamlit 工具。
3. 不做完整盘后复盘收益统计；只展示现有分钟线和信号 JSONL。
4. 不新增新的数据源；实时采集仍只使用现有百度 WebSocket。
5. 不在第一版做复杂持仓文件管理；页面先使用“有底仓/无底仓”开关映射现有信号入口。

## 工作区结构 / 架构

```text
apps/intraday-t/
  src/intraday_t/
    web_app.py          # Streamlit 页面入口
    web_runtime.py      # 后台采集会话、状态查询、数据读取辅助
  tests/
    test_web_runtime.py # 后台采集和视图数据单测
  README.md             # Web UI 启动说明
```

数据流：

```text
Streamlit 表单
  -> WebCollectorSession.start(codes, day)
  -> baidu_ws.stream_snapshots -> RawSnapshotWriter -> raw JSONL
  -> refresh_signals(base_dir, codes, day, has_position)
  -> aggregate_code -> generate_signals_for_code -> minute/signals JSONL
  -> load_dashboard_data -> Web UI 表格/卡片
```

## 数据模型 / Schema

Web 层只新增轻量视图模型，不改变现有 JSONL schema。

```python
@dataclass(slots=True)
class CollectorStatus:
    running: bool
    codes: list[str]
    day: str | None
    started_at: str | None = None
    stopped_at: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    latest: dict[str, Snapshot] = field(default_factory=dict)
    error: str | None = None

@dataclass(slots=True)
class DashboardCodeData:
    code: str
    raw_count: int
    minute_count: int
    signal_count: int
    latest_snapshot: dict[str, Any] | None
    latest_signal: dict[str, Any] | None
    minute_rows: list[dict[str, Any]]
    signal_rows: list[dict[str, Any]]
```

约束：

1. `CollectorStatus.latest` 仅保存在当前 Python 进程内，用于页面状态展示；真实数据仍以 JSONL 为准。
2. 停止采集只停止后台线程和 async loop，不删除已落盘数据。
3. 若 WebSocket 失败，状态里记录 `error`，页面显示错误并允许重新启动。

## 接口设计

新增本地网页启动命令：

```bash
cd apps/intraday-t
python scripts/intraday_web.py
```

`pyproject.toml` 增加 Streamlit 依赖和可选脚本入口：

```toml
dependencies = [
    "websockets>=12.0",
    "streamlit>=1.58",
]

[project.scripts]
intraday-web = "intraday_t.web_app:main"
```

内部接口：

```python
class WebCollectorSession:
    def start(self, codes: list[str], base_dir: Path, day: str | None, timeout: float) -> None: ...
    def stop(self) -> None: ...
    def status(self) -> CollectorStatus: ...

def refresh_signals(base_dir: Path, codes: list[str], day: str | None, *, has_position: bool, opening_minutes: int) -> list[str]: ...

def load_dashboard_data(base_dir: Path, codes: list[str], day: str | None, *, limit: int = 200) -> list[DashboardCodeData]: ...
```

页面操作：

1. 参数区：`codes`、`day`、`data_dir`、`timeout`、`opening_minutes`、`has_position`、`auto_refresh`。
2. 控制区：启动采集、停止采集、刷新信号。
3. 状态区：采集是否运行、每只股票快照数量、最新价/VWAP/涨跌幅、错误信息。
4. 看板区：最新信号卡片、信号历史表、分钟线表、原始数据计数。

## 子系统设计

### 后台采集会话

`WebCollectorSession` 使用后台线程持有独立 asyncio event loop，在线程内消费 `stream_snapshots()` 并通过 `RawSnapshotWriter` 落盘。线程内维护计数、最新快照和错误信息；页面 rerun 时从 `st.session_state` 取同一个会话实例。

启动规则：

1. 已运行时再次启动同一会话不重复创建线程。
2. 若用户切换股票、日期或数据目录后启动，先停止旧会话，再启动新会话。
3. 停止时设置 thread-safe stop event，并等待线程短时间退出；如果 WebSocket 阻塞，依赖 timeout 周期性返回控制权。

### 数据刷新

`refresh_signals()` 不直接依赖 Streamlit，复用 `monitor.run_once()` 或等价链路，完成 raw -> minute -> signals。页面点击“刷新信号”时调用一次；开启自动刷新时由 Streamlit 定时 rerun 后再调用。

### 展示层

`web_app.py` 只负责布局和调用 `web_runtime.py`，不直接解析 JSONL 或控制线程。表格字段优先显示交易所操作关心的信息：时间、价格、VWAP、涨跌幅、信号、强度、动作、原因、失效条件、策略、日内状态。

## 配置

第一版不新增配置文件。页面默认参数来自现有代码：

1. `data_dir` 默认 `apps/intraday-t/data`。
2. `day` 默认今天，允许手动输入历史日期。
3. `timeout` 默认 30 秒，用于让后台采集可响应停止。
4. `opening_minutes` 默认 5。

## 安全策略

1. 默认不下单：页面所有按钮只做采集、聚合、信号生成和展示，不调用券商交易接口。
2. 风险提示：页面顶部固定提示“仅供人工辅助，不构成交易建议，不自动交易”。
3. 输入校验：股票代码走现有 `parse_codes()`，非法代码在页面显示错误，不启动采集。
4. 本地运行：不设计外网部署和鉴权，避免误暴露本地数据和操作入口。

## 改动范围

- `apps/intraday-t/pyproject.toml`：增加 `streamlit` 依赖和 `intraday-web` 脚本入口。
- `apps/intraday-t/src/intraday_t/web_runtime.py`：新增可测试的后台采集会话、信号刷新和看板数据读取。
- `apps/intraday-t/src/intraday_t/web_app.py`：新增 Streamlit 页面。
- `apps/intraday-t/tests/test_web_runtime.py`：新增代码解析、数据加载、刷新信号和会话状态单测。
- `apps/intraday-t/README.md`：补充 Web UI 使用方式和边界说明。

## 假设

- ⚠ 本地环境允许安装并运行 Streamlit；如未安装，需先执行 `python -m pip install -e apps/intraday-t`。
- ⚠ Streamlit 页面只需要服务单个本机用户；多浏览器会话同时控制采集不作为第一版目标。
- ⚠ 百度 WebSocket 在交易时段可用；非交易时段或网络失败时，页面只展示错误和已有本地数据。

## 风险

- Streamlit rerun 可能导致采集控制重复初始化；兜底是把会话对象保存在 `st.session_state`，Web 层不使用全局自动启动。
- 后台 WebSocket 阻塞会影响停止响应；兜底是采集 timeout 采用较短默认值，并在循环里检查 stop event。
- 页面自动刷新和手动刷新可能同时读写 JSONL；兜底是保持现有按行追加/整文件写入方式，读取失败时展示空表或错误，不删除数据。
- 把采集、信号和 UI 混写会降低可测性；兜底是所有非 UI 逻辑放入 `web_runtime.py` 并用单测覆盖。

## 验收链路

运行测试：

```bash
cd apps/intraday-t
python -m pytest tests/ -v
```

启动页面冒烟：

```bash
cd apps/intraday-t
python scripts/intraday_web.py
```

必须证明：

1. 页面可输入 `002463` 和交易日，读取现有样例 raw/minute/signals 数据并展示最新信号。
2. 点击“刷新信号”会生成或更新 minute/signals JSONL，且页面能看到最新结果。
3. 点击“启动采集”会创建后台采集会话，状态显示运行中和已订阅代码；点击“停止采集”后状态变为已停止。
4. 非法股票代码不会启动采集，会在页面显示校验错误。
5. 现有采集、聚合、信号、monitor、live 单测不回退。

## 后续实现顺序

建议按最小可验证链路实现：

1. 写 `web_runtime` 数据读取测试，验证已有 JSONL 能转成页面视图数据。
2. 写 `refresh_signals` 测试，验证能复用 raw 生成 minute/signals 并返回最新信号文本。
3. 写 `WebCollectorSession` 状态测试，使用 fake async stream 验证启动、计数、停止和错误记录。
4. 实现 `web_runtime.py`，先不依赖 Streamlit。
5. 实现 `web_app.py`，连接表单、按钮、状态和数据表。
6. 更新 `pyproject.toml` 和 README，补充启动命令与风险边界。
7. 运行 `python -m pytest tests/ -v`，再做 Streamlit 启动冒烟。
8. 查找并同步 `memory/process.md`，如不存在则在最终说明中标注。

## 参考

- 现有设计文档：`docs/intraday-t-tool-design.md`
- 已完成信号升级：`docs/specs/intraday-t-strategy-upgrade.md`
- 实时采集入口：`apps/intraday-t/src/intraday_t/live.py`
- 终端监控入口：`apps/intraday-t/src/intraday_t/monitor.py`
- 百度 WebSocket：`apps/intraday-t/src/intraday_t/baidu_ws.py`
