# A 股数据源与接口记录

本文记录当前调研过、已验证或计划验证的 A 股数据源、仓库、接口和适用场景，用于后续构建“开盘实时采集 + 日内做 T 分析 + 焚诀战法研究”工具链。

## 总体分层

| 层级 | 数据源 | 主要用途 | 当前建议 |
|---|---|---|---|
| 实时层 | 百度财经 WebSocket | 开盘后指定股票实时行情推送 | 适合做盘中采集与提醒 |
| 通达信在线层 | `easy_tdx` / `mootdx` | K 线、分时、报价、逐笔、板块、指标 | `easy_tdx` 作为主用通达信源，`mootdx` 仅作 fallback |
| 选股层 | 同花顺问财 Skill | 自然语言选股、技术条件初筛 | 适合批量初筛，结果需本地二次计算确认 |
| 补充数据层 | `a-stock-data` Skill | 研报、新闻、龙虎榜、资金、热点 | 适合补充催化和热度，但东财接口要限流 |
| 舆情线索层 | `skills/twitter-user-posts/cache` | 本地 X/Twitter 缓存线索 | 只作市场关注线索，不作事实依据 |

## 百度财经 WebSocket

### 地址

```text
wss://finance-ws.pae.baidu.com
```

### 已验证结论

- WebSocket 握手可成功。
- 服务不会主动推首包，必须发送订阅消息。
- A 股订阅 `market` 使用 `ab` 成功。
- `financeType` 必须使用 `stock`；仅传 `type: stock` 未收到数据。

### 订阅消息示例

```json
{
  "method": "subscribe",
  "source": "pc-web",
  "product": "snapshot",
  "items": [
    {
      "code": "002463",
      "market": "ab",
      "financeType": "stock"
    }
  ]
}
```

### Python 最小示例

```python
import asyncio
import json
import websockets


async def main():
    url = "wss://finance-ws.pae.baidu.com"
    headers = {
        "Origin": "https://gushitong.baidu.com",
        "User-Agent": "Mozilla/5.0",
    }

    async with websockets.connect(url, additional_headers=headers) as ws:
        await ws.send(json.dumps({
            "method": "subscribe",
            "source": "pc-web",
            "product": "snapshot",
            "items": [
                {"code": "002463", "market": "ab", "financeType": "stock"}
            ],
        }, ensure_ascii=False))

        msg = await ws.recv()
        print(msg)


asyncio.run(main())
```

### 实测返回字段摘要

以 `002463 沪电股份` 为例，返回包含：

- `cur.price`：当前价
- `cur.ratio`：涨跌幅
- `cur.increase`：涨跌额
- `cur.avgPrice`：均价
- `pankouinfos`：盘口/行情字段列表

`pankouinfos` 中实测出现：

| ename | name | 含义 |
|---|---|---|
| `open` | 今开 | 开盘价 |
| `high` | 最高 | 最高价 |
| `low` | 最低 | 最低价 |
| `preClose` | 昨收 | 昨日收盘价 |
| `volume` | 成交量 | 当日成交量 |
| `amount` | 成交额 | 当日成交额 |
| `turnoverRatio` | 换手率 | 当日换手率 |

### 适用场景

- 开盘后订阅指定股票实时行情。
- 盘中落盘 JSONL，用于事后复盘。
- 做日内高抛低吸信号分析，例如 VWAP 偏离、分时高低点、冲高回落、急杀修复。

### 注意事项

- 需要实盘多日观察稳定性和推送频率。
- 不适合历史回测，历史数据仍应使用通达信或其他 K 线源。
- 建议只订阅用户指定股票，不要全市场订阅。

## `mootdx/mootdx`

仓库：<https://github.com/mootdx/mootdx>

### 定位

通达信数据读取的成熟 Python 封装，当前项目 `a-stock-data` 已把 `mootdx` 作为行情源之一。后续新功能优先使用 `easy_tdx`，`mootdx` 只作为兼容和故障 fallback。

### 能力

- 在线通达信行情读取。
- K 线、指数、分钟线。
- 本地通达信离线数据读取。
- 财务文件、F10 等。

### 示例

```python
from mootdx.quotes import Quotes

client = Quotes.factory(market="std")

# 日 K
bars = client.bars(symbol="002463", category=4, offset=100)

# 实时报价
quotes = client.quotes(symbol=["002463", "600941"])

# 分钟线
minute = client.minute(symbol="002463")
```

### 当前建议

- 不再作为新功能主数据源。
- 保留现有 `a-stock-data` 中的 `mootdx` 用法，避免一次性重构引入风险。
- 当 `easy_tdx` 安装不可用、服务器连接失败或某字段缺失时，用 `mootdx` 兜底。
- 适合继续承担兼容性 fallback，例如历史 K 线、基础行情、F10/财务等。

## `handsomejustin/easy_tdx`

仓库：<https://github.com/handsomejustin/easy_tdx>

### 定位

新一代通达信 Python SDK，支持 CLI、同步/异步 API、在线数据、离线数据和技术指标计算。默认 JSON 输出，适合 AI Agent 和策略研究工具链。后续新开发优先使用 `easy_tdx` 作为主通达信数据源。

### 重点能力

- A 股实时批量报价。
- K 线与分钟线。
- 逐笔成交。
- 板块列表、板块成分、板块汇总、板块排行。
- 资金流、集合竞价、市场异动。
- 本地通达信离线数据读取。
- 内置技术指标，例如 `MACD`、`KDJ`、`RSI`、`BOLL`、`BIAS_SIGNAL`、`ZHUOYAO`。

### CLI 示例

```bash
# 服务器测速
easy-tdx ping

# 实时报价
easy-tdx quote "SZ 002463,SH 600941" --table

# A 股按成交额/涨幅等排序
easy-tdx quote-list A --count 50 --table

# K 线
easy-tdx kline SZ 002463 --count 120 --table

# 技术指标：捉妖大师
easy-tdx indicator ZHUOYAO -m SZ -c 002463 --count 30 --table

# 技术指标：30 日乖离率信号
easy-tdx indicator BIAS_SIGNAL -m SZ -c 002463 --count 60 --table

# 板块排行
easy-tdx board-ranking --type HY --top 20 --table
easy-tdx board-ranking --type GN --sort-by amount --table

# 个股所属板块
easy-tdx belong-board SZ 002463 --table

# 资金流
easy-tdx capital-flow SZ 002463 --table

# 集合竞价
easy-tdx auction SZ 002463 --table

# 市场异动
easy-tdx unusual SH --count 100 --table
```

### Python API 示例

```python
from easy_tdx import MacClient, Market, Period, Adjust

with MacClient.from_best_host() as client:
    df = client.get_stock_kline(
        Market.SZ,
        "002463",
        Period.DAILY,
        count=120,
        adjust=Adjust.QFQ,
    )

    quote = client.get_stock_quotes([(Market.SZ, "002463")])

    indicators = client.get_stock_kline_with_indicators(
        Market.SZ,
        "002463",
        indicators=["ZHUOYAO", "BIAS_SIGNAL"],
        count=60,
    )
```

### 对“焚诀”的价值

`easy_tdx` 作为主用通达信源，更适合做战法研发、盘中监控和回测：

- `ZHUOYAO`：用于短中长趋势共振过滤。
- `BIAS_SIGNAL`：用于回踩/乖离修复确认。
- `board-ranking`：用于识别当日行业/概念主线。
- `board-summary`：用于判断板块成交额、主力净流入、涨跌家数。
- `auction`：用于集合竞价战法。
- `unusual`：用于盘中异动捕捉。
- `offline daily/min`：用于本地历史数据回测。

### 当前建议

- 新功能优先接入 `easy_tdx`。
- `mootdx` 只在 `easy_tdx` 不可用时 fallback。
- 先本机验证安装和核心命令可用性。
- 若稳定，可封装为主通达信数据适配器，例如 `EasyTdxProvider`。
- 适配器层应保留统一接口，避免业务代码直接依赖具体库。

## 同花顺问财 Skill

本地 skill：`.claude/skills/tonghuashun-skills`

### 定位

适合自然语言选股与批量条件初筛。

### 当前已用场景

- A 股均线回踩筛选。
- 按 `量比`、`均线向上`、`收盘价`、`MA5/10/20/30`、`换手率`、`涨跌幅` 组合筛选。

### 使用注意

- 问财返回的“接近均线”等判断不能直接相信。
- 必须拿到收盘价和 MA 值后本地计算偏离率。
- 日期字段要检查，例如 `收盘价[20260605]`、`ma5[20260605]`。
- 如果当日字段不可用，要回退到最近已完成交易日。

### 示例查询语句

```text
A股，今日收盘价，今日5日均线，今日10日均线，今日20日均线，今日30日均线，今日量比，今日涨跌幅，今日换手率，5日均线向上，10日均线向上，20日均线向上，30日均线向上，量比小于1.25，股票代码不以688开头，股票代码不以30开头
```

### 本地二次过滤示例

```python
deviation = (close - ma) / ma * 100
selected = abs(deviation) <= 2.5
```

## `a-stock-data` Skill

本地 skill：`skills/a-stock-data/SKILL.md` 或 `.claude/skills/a-stock-data/SKILL.md`

### 定位

A 股补充数据工具包，覆盖行情、研报、新闻、龙虎榜、资金、热点、财务、公告等。

### 重点接口

| 能力 | 函数/来源 | 用途 |
|---|---|---|
| 腾讯行情 | `tencent_quote` | 实时价、涨跌幅、成交额、换手率、市值、量比 |
| 东财研报 | `eastmoney_reports` | 近 180 天研报数量、机构、评级、EPS 预测 |
| 同花顺热点 | `ths_hot_reason` | 当日强势股题材归因 |
| 龙虎榜 | `daily_dragon_tiger` / `dragon_tiger_board` | 当日/近 N 日龙虎榜、净买额 |
| 东财新闻 | `eastmoney_stock_news` | 个股新闻、标题、摘要、链接 |
| 资金流 | `eastmoney_fund_flow_minute` / `stock_fund_flow_120d` | 主力资金流、日级资金流 |

### 使用注意

- 行情优先用通达信/腾讯，东财只用于独有数据。
- 东财接口必须串行限流，不要并发批量扫 200+ 股票。
- 批量候选较多时，建议先用低风控数据初排，再对 Top N 补研报、新闻、龙虎榜。

## 本地 X/Twitter 缓存

目录：`skills/twitter-user-posts/cache`

### 定位

本地 X 缓存只作为市场关注线索，不作为事实依据。

### 可搜索内容

- 股票代码，例如 `002463`。
- 股票名称，例如 `沪电股份`。
- 题材关键词，例如 `PCB`、`AI算力`、`先进封装`、`光模块`、`电力`、`半导体`、`机器人`。
- 图片 OCR 字段，例如 `ocr_text`、`ocr_media[].text`。

### 分类建议

| 类型 | 含义 | 权重建议 |
|---|---|---|
| 直接提及个股 | 文本/OCR 命中股票代码或名称 | 高 |
| 产业链相关 | 命中公司所属产业链关键词 | 中 |
| 同题材相关 | 命中共同题材但未直接指向公司 | 中低 |
| 弱相关 | 泛行业/泛情绪内容 | 低 |

### 注意事项

- 不重新抓取 X，只读本地 cache。
- OCR 可能识别错误。
- 传闻类内容不能作为事实依据，只能作为关注度线索。

## 开盘实时采集 + 日内做 T 分析方案

### 前提

A 股普通账户是 `T+1`，日内做 T 必须基于已有底仓，不能当天买入当天卖出同一批新仓。

### MVP 目标

第一版做“辅助决策”，不做自动交易：

1. 输入指定股票列表。
2. 开盘后通过百度 WebSocket 订阅实时快照。
3. 本地按股票落盘 JSONL。
4. 每分钟聚合一次分时指标。
5. 输出“高抛 / 低吸 / 观望”信号和理由。

### 建议目录结构

```text
data/intraday/
└── YYYY-MM-DD/
    ├── 002463.jsonl
    ├── 600941.jsonl
    └── summary.json
```

### JSONL 记录建议字段

```json
{
  "ts": "2026-06-05T09:31:02+08:00",
  "code": "002463",
  "name": "沪电股份",
  "price": 133.22,
  "ratio": -5.40,
  "increase": -7.60,
  "avg_price": 136.45,
  "open": 137.10,
  "high": 141.28,
  "low": 131.81,
  "pre_close": 140.82,
  "amount": 13031904560,
  "volume": 95505600,
  "turnover_ratio": 4.97,
  "raw": {}
}
```

### 分析指标

| 指标 | 用途 |
|---|---|
| VWAP/均价线偏离 | 判断高抛低吸位置 |
| 分时高低点 | 判断冲高回落、急杀修复 |
| 最近 1/3/5 分钟成交额变化 | 判断放量/缩量 |
| 相对开盘涨跌 | 判断开盘强弱 |
| 相对昨收涨跌 | 判断全天强弱 |
| 回撤幅度 | 判断是否过度杀跌 |
| 反弹幅度 | 判断是否弱修复或强修复 |

### 候选日内做 T 策略

#### 1. 高开冲高回落型

条件示例：

- 开盘高开。
- 前 10-30 分钟快速冲高。
- 二次冲高不过前高。
- 价格跌破 VWAP 或均价线。
- 成交额放大但价格不再创新高。

动作：提示“高抛底仓”。

#### 2. 低开急杀修复型

条件示例：

- 低开或快速下杀。
- 二次下探不破前低。
- 下杀成交缩量。
- 价格重新站上短周期均价或 VWAP。

动作：提示“低吸回补”。

#### 3. VWAP 回踩不破型

条件示例：

- 个股全天维持 VWAP 上方。
- 回踩 VWAP 附近缩量。
- 再次放量上穿短周期高点。

动作：提示“低吸或持有”。

#### 4. 冲高不过前高型

条件示例：

- 两次冲高。
- 第二次冲高量能弱于第一次。
- 涨幅接近前高但未突破。

动作：提示“减仓/高抛”。

### 禁止交易区

| 场景 | 原因 |
|---|---|
| 开盘前 3-5 分钟 | 噪声极大，容易误判 |
| 接近涨跌停 | 流动性和成交规则特殊 |
| 极端放量但盘口失真 | 容易是消息冲击或资金对倒 |
| 大盘/板块急跌 | 个股信号容易失效 |
| 无底仓 | 普通账户不能真正做 T |

## 后续落地建议

### 第零阶段：通达信主备适配器

新增适配器建议：

```text
apps/intraday-t/src/intraday_t/data/easy_tdx_provider.py
apps/intraday-t/src/intraday_t/data/tdx_fallback.py
```

主备策略：

- 主数据源：`easy_tdx`。
- fallback：`mootdx`。
- 业务代码只调用统一接口，不直接依赖具体库。
- 当 `easy_tdx` 命令不存在、Python 包未安装、连接通达信服务器失败、字段缺失或返回空时，自动降级到 `mootdx`。

统一接口建议：

```python
class TdxProvider:
    def quote(self, codes: list[str]) -> dict: ...
    def kline(self, code: str, period: str = "daily", count: int = 120) -> list[dict]: ...
    def minute(self, code: str) -> list[dict]: ...
    def indicators(self, code: str, names: list[str], count: int = 120) -> list[dict]: ...
```

验收方式：

- `easy_tdx` 可用时，报价/K线/指标走 `easy_tdx`。
- 人为禁用 `easy_tdx` 时，同一调用能回退到 `mootdx`。
- 返回字段归一化为统一结构，例如 `code/name/price/change_pct/amount/turnover/vol_ratio`。

### 第一阶段：采集器

新增脚本建议：

```text
apps/intraday-t/scripts/intraday_collector.py
```

功能：

- 读取股票列表。
- 订阅百度财经 WebSocket。
- 解析快照字段。
- 落盘 JSONL。
- 支持 Ctrl+C 安全退出。

### 第二阶段：分时分析器

新增脚本建议：

```text
apps/intraday-t/scripts/intraday_t_analyzer.py
```

功能：

- 读取当天 JSONL。
- 聚合 1 分钟数据。
- 计算 VWAP、分时高低点、成交额变化。
- 输出做 T 信号和理由。

### 第三阶段：焚诀规则化

把稳定信号沉淀为规则：

```text
焚诀：缩量回踩均价线
焚诀：冲高不过前高
焚诀：低开急杀修复
焚诀：板块共振低吸
```

每条焚诀都应包含：

- 适用场景。
- 触发条件。
- 失效条件。
- 止损/止盈建议。
- 是否需要底仓。
- 需要的数据字段。
- 回测结果。
