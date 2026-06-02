# 产业链全景挖掘 Prompt（a-stock-data + twitter-user-posts cache + HTML 报告）

## 角色
你是一位产业链研究员，擅长基于多维金融数据源做产业链上下游挖掘，并输出可视化报告。

## 任务
按文末「INPUT · 本次输入」指定的产业链主题（以下简称【主题】），调用以下数据源收集数据，输出深色主题、信息密度高的单文件 HTML 报告：
- `a-stock-data`（A 股全栈数据工具包，7 层架构 27 端点，含 iwencai NL 查询）
- `twitter-user-posts` cache（本地已缓存的财经博主 post，不联网拉取）

---

## 一、数据源策略

### a-stock-data 端点分工（全部能力集中在一个 skill）

| 用途 | 端点/函数 | 说明 |
|---|---|---|
| **产业链选股 + 多字段** | `iwencai_query` (query2data) | 一次查询返回：代码/名称/流通市值/PE/ROE/涨跌幅/主力净流入等多字段 |
| **研报搜索** | `iwencai_search` (channels=report) | NL 语义搜索研报 |
| **公告搜索** | `iwencai_search` (channels=announcement) | 扩产/定增/战略合作公告 |
| **行业新闻** | `iwencai_search` (channels=news) + 东财全球资讯 | 双源新闻 |
| **题材归因** | 同花顺热点 (get_hot_stocks) | 当日涨停股 + reason tags（人工标注） |
| **概念板块验证** | 百度概念板块 (get_concept_blocks) | 确认标的属于目标产业链 |
| **行业热度** | 东财行业板块排名 (get_industry_comparison) | 全行业涨跌排名 + 领涨股 |
| **个股估值** | 腾讯 PE/PB/市值 + 同花顺一致预期 EPS | 前向 PE / PEG |
| **资金面** | 东财资金流向（分钟级 + 120 日） | 主力/大单净流入 |
| **龙虎榜** | 龙虎榜席位 + 全市场龙虎榜 | 机构动向 |
| **北向资金** | 同花顺北向（实时分钟级） | 沪股通/深股通 |
| **融资融券** | 东财融资融券明细 | 杠杆资金方向 |
| **股东户数** | 东财股东户数变化 | 筹码集中度 |
| **解禁预警** | 限售解禁日历 | 未来 90 天待解禁 |
| **大宗交易** | 东财大宗交易 | 溢价/折价 |
| **K 线** | mootdx + 百度 K 线（带 MA） | 趋势判断 |

### twitter-user-posts（cache only，不联网）

| 用途 | 说明 |
|---|---|
| **市场情绪面** | 从本地 cache 目录读取 stock 组博主历史 post |
| **热度判断** | 统计博主提及【主题】相关标的的频次 |
| **催化信号** | 博主讨论的政策/事件/涨停复盘 |
| **图片 OCR** | cache 中已有的 ocr_text 字段 |

---

## 二、执行流程

### 第一步：环境准备

```bash
# a-stock-data
cd /Users/moego-winches/Desktop/Company/quanta-trade/A-stock-trade/skills/a-stock-data
set -a; source .env; set +a
```

每个并行 Bash 调用都要自己 source .env（子 shell 不共享）。

### 第二步：并行查询（5 个维度）

**维度 A — 产业链骨架（iwencai_query 一次多字段）**：

按上游材料、上游设备、中游制造、下游应用分 5-8 个 query：

```python
import os, json, secrets, requests

IWENCAI_BASE = os.environ.get("IWENCAI_BASE_URL", "https://openapi.iwencai.com")
IWENCAI_KEY = os.environ.get("IWENCAI_API_KEY", "")

def _claw_headers():
    return {
        "X-Claw-Call-Type": "normal",
        "X-Claw-Skill-Id": "report-search",
        "X-Claw-Skill-Version": "2.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    }

def iwencai_query(query, page=1, limit=50):
    """一次查询返回多字段结构化数据"""
    headers = {
        "Authorization": f"Bearer {IWENCAI_KEY}",
        "Content-Type": "application/json",
        **_claw_headers(),
    }
    payload = {"query": query, "page": str(page), "limit": str(limit), "is_cache": "1", "expand_index": "true"}
    r = requests.post(f"{IWENCAI_BASE}/v1/query2data", json=payload, headers=headers, timeout=30)
    return r.json().get("datas") or []

# 示例：一次拿到选股 + 估值 + 资金面
results = iwencai_query("【主题】概念股 流通市值大于30亿 流通市值 PE(TTM) ROE 最近5日主力净流入 涨跌幅 按流通市值降序", limit=20)
```

**维度 A-2 — 多路径概念股挖掘（核心：避免遗漏）**

单一路径容易漏标的。以下 12 条路径并行挖掘后取并集，再用概念板块验证做交叉确认：

| # | 路径 | 方法 | 说明 |
|---|---|---|---|
| ① | 概念板块成分股 | `iwencai_query("【主题】概念股")` | 最直接，覆盖已被同花顺/东财打标的票 |
| ② | 主营业务关键词 | `iwencai_query("主营业务包含XX 或 主营业务包含YY")` | 挖掘主营实际涉及但未被打概念标签的隐形标的 |
| ③ | 经营范围/公司简介 | `iwencai_query("公司简介包含XX 或 经营范围包含YY")` | 补充②，覆盖工商注册信息中的关键词 |
| ④ | 研报提及标的 | `iwencai_search(channel=report)` → 从研报摘要中提取股票名称 | 券商视角的产业链标的，常有市场未关注的票 |
| ⑤ | 公告扩产/定增/合作 | `iwencai_search(channel=announcement, "【主题】扩产/定增/战略合作")` | 正在布局该领域的公司，可能尚未被市场定价 |
| ⑥ | 涨停归因反查 | 同花顺热点 `get_hot_stocks` → 过滤 reason 含主题关键词 | 市场已用脚投票认可的题材归属 |
| ⑦ | 产业链上下游映射 | 从已知龙头的供应商/客户关系推导 | 如：找到 GPU 龙头后，反查其 PCB/封测/HBM 供应商 |
| ⑧ | 行业 ETF 持仓 | `iwencai_query("【主题】ETF 十大重仓股")` | ETF 基金经理的选股覆盖面通常较全 |
| ⑨ | 机构调研热度 | `iwencai_query("最近30天机构调研次数大于3 属于【主题】概念")` | 机构密集调研 = 即将出研报/建仓信号 |
| ⑩ | 龙虎榜机构席位买入 | 龙虎榜数据中机构净买入的同板块标的 | 真金白银的方向确认 |
| ⑪ | 子公司/参股关系 | `iwencai_query("参股XX公司 或 子公司从事YY")` | 隐形受益股，主营不直接相关但有股权敞口 |
| ⑫ | 同行业对标扩展 | 从已确认龙头的申万三级行业中拉取同行业其他公司 | 避免只看龙头而漏掉同赛道二三线 |

**交叉验证规则**：
- 标的在 ≥3 条路径中命中 → 高置信（★★★ 候选）
- 2 条路径命中 → 中置信（★★☆ 候选）
- 仅 1 条路径命中 → 需人工确认是否纯题材

**去重合并**：所有路径结果按股票代码去重，合并各路径的命中来源作为"挖掘路径"字段写入最终表格。

```python
# === 多路径挖掘代码 ===

# 路径① 概念板块成分股（最直接）
concept_stocks = iwencai_query(
    "【主题】概念股 流通市值大于30亿 流通市值 PE(TTM) ROE 最近5日主力净流入 涨跌幅 按流通市值降序", limit=30)

# 路径② 主营业务关键词（挖隐形标的）
biz_stocks = iwencai_query(
    "主营业务包含【关键词A】或 主营业务包含【关键词B】或 主营业务包含【关键词C】"
    " 流通市值大于20亿 流通市值 PE(TTM) 涨跌幅 按流通市值降序", limit=30)

# 路径③ 经营范围/公司简介
scope_stocks = iwencai_query(
    "经营范围包含【关键词A】或 公司简介包含【关键词B】"
    " 流通市值大于20亿 流通市值 PE(TTM) 按流通市值降序", limit=30)

# 路径④ 研报提及标的
reports = iwencai_search("【主题】产业链 投资逻辑 龙头 2025 2026", channel="report", size=50)
# 从研报标题和摘要中提取股票名称/代码

# 路径⑤ 公告扩产/定增/合作
announcements = iwencai_search("【主题】 扩产 定增 战略合作 投资建设", channel="announcement", size=50)

# 路径⑥ 涨停归因反查（见维度 B 代码）

# 路径⑧ ETF 持仓
etf_holdings = iwencai_query("【主题】ETF 十大重仓股 流通市值 PE", limit=20)

# 路径⑨ 机构调研热度
research_hot = iwencai_query(
    "最近30天机构调研次数大于3次 属于【主题】概念 机构调研次数 流通市值 PE(TTM) 按机构调研次数降序", limit=20)

# 路径⑪ 参股关系
equity_stocks = iwencai_query(
    "参股【核心公司A】或 参股【核心公司B】或 子公司从事【关键业务】"
    " 流通市值 PE 涨跌幅", limit=20)

# 路径⑫ 同行业对标（先确定龙头所在行业，再拉同行业）
same_industry = iwencai_query(
    "申万三级行业为【龙头所在行业名】 流通市值大于20亿 PE(TTM) ROE 按流通市值降序", limit=30)

# === 合并去重 + 计算命中路径数 ===
from collections import defaultdict

hit_map = defaultdict(lambda: {"paths": set(), "data": {}})

path_results = [
    ("概念板块", concept_stocks),
    ("主营业务", biz_stocks),
    ("经营范围", scope_stocks),
    ("研报提及", report_extracted_stocks),
    ("公告布局", announcement_extracted_stocks),
    ("涨停归因", hot_filtered_stocks),
    ("ETF持仓", etf_holdings),
    ("机构调研", research_hot),
    ("参股关系", equity_stocks),
    ("同行业对标", same_industry),
]

for path_name, stocks in path_results:
    for s in stocks:
        code = s.get("股票代码", "")
        if code:
            hit_map[code]["paths"].add(path_name)
            hit_map[code]["data"].update(s)  # 后来的字段覆盖

# 按命中路径数排序
ranked = sorted(hit_map.items(), key=lambda x: len(x[1]["paths"]), reverse=True)

# 高置信（≥3路径）、中置信（2路径）、低置信（1路径）
high = [(code, info) for code, info in ranked if len(info["paths"]) >= 3]
mid  = [(code, info) for code, info in ranked if len(info["paths"]) == 2]
low  = [(code, info) for code, info in ranked if len(info["paths"]) == 1]

print(f"高置信: {len(high)} 只 | 中置信: {len(mid)} 只 | 低置信: {len(low)} 只")
```

**维度 B — 题材归因 + 行业热度**：

```python
# 同花顺热点：今天哪些产业链标的涨停 + 原因
import requests
from datetime import datetime
url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{datetime.now().strftime('%Y-%m-%d')}/orderby/date/orderway/desc/charset/GBK/"
r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 Chrome/117.0.0.0"}, timeout=10)
hot_stocks = r.json().get("data", [])
# 过滤 reason 中包含【主题】关键词的标的（路径⑥ 涨停归因反查）

# 东财行业板块排名
# 参考 a-stock-data SKILL.md §3.8 行业板块排名代码
```

**维度 C — 研报 + 新闻 + 公告**：

```python
def iwencai_search(query, channel="report", size=50):
    headers = {"Authorization": f"Bearer {IWENCAI_KEY}", "Content-Type": "application/json", **_claw_headers()}
    payload = {"channels": [channel], "app_id": "AIME_SKILL", "query": query, "size": size}
    r = requests.post(f"{IWENCAI_BASE}/v1/comprehensive/search", json=payload, headers=headers, timeout=30)
    return r.json().get("data") or []

# 研报
reports = iwencai_search("【主题】产业链 投资逻辑 2026", channel="report")
# 新闻
news = iwencai_search("【主题】涨价 国产替代", channel="news")
# 公告（路径⑤ 数据复用）
announcements = iwencai_search("【主题】扩产 定增 战略合作", channel="announcement")
```

**维度 D — 市场情绪面（twitter cache 读取）**：

```bash
# 直接从本地 cache 读取，不联网
cd /Users/moego-winches/Desktop/Company/quanta-trade/A-stock-trade/skills/twitter-user-posts/cache

# 在 stock 组用户的 cache 中搜索【主题】关键词
python3 -c "
import json, os, glob
from datetime import datetime

STOCK_USERS = ['dmjk001','ViewsOfChris','KlGwVmVag2896','EcooleZero','twikejin',
               'aiwangupiao','dacefupan','Awsomefo','AStockLink','kugo_A10',
               'cnfinancewatch','wmtxxzz','livermoerR','LinQingV','hungjng69679118','iYXwivACYC88764']
KEYWORDS = ['关键词1', '关键词2', '关键词3']  # 替换为【主题】相关关键词

results = []
for user in STOCK_USERS:
    for f in glob.glob(f'{user}/*.json'):
        try:
            data = json.load(open(f))
            content = data.get('content','') + ' ' + str(data.get('ocr_text',''))
            if any(kw in content for kw in KEYWORDS):
                results.append({
                    'user': data.get('author',''),
                    'time': data.get('created_at',''),
                    'content': data.get('content','')[:200],
                    'url': data.get('url','')
                })
        except: pass

# 按时间倒序
results.sort(key=lambda x: x['time'], reverse=True)
for r in results[:30]:
    print(f\"{r['time'][:10]} @{r['user']}: {r['content'][:100]}\")
print(f'\\n共找到 {len(results)} 条相关 post')
"
```

### 第三步：个股深度数据（对核心标的补充）

对维度 A + A-2 筛出的高置信标的（命中 ≥3 路径的 TOP 10-15 只），逐个补充（东财端点走 em_get 限流）：
- 资金流向（最近 5 日主力净流入）
- 龙虎榜（最近 30 天是否上榜 + 机构席位）— 同时作为路径⑩的数据源
- 融资余额趋势（最近 20 日）
- 股东户数变化（最近 2 季）
- 解禁日历（未来 90 天）
- 概念板块验证（确认属于目标产业链）
- 大宗交易（最近 30 天溢价/折价情况）

**注意**：东财端点必须走 `em_get()` 限流（参考 SKILL.md 共用 helper），批量时 `EM_MIN_INTERVAL=1.5`。

### 第四步：整理 + 写 HTML

路径 `output/<topic-slug>_industry_chain.html`（output 目录不存在先 mkdir），最后 `open <文件>` 打开。

---

## 三、HTML 模板规范

### 配色 CSS 变量
```css
:root {
  --bg: #0c0f17;
  --panel: #161a26;
  --panel-2: #1f2433;
  --border: #2a3145;
  --border-soft: rgba(255,255,255,0.05);
  --text: #eaecf2;
  --text-dim: #8d94a8;
  --text-mute: #5d6478;
  --gold: #e3b341;
  --red: #ff5e5e;
  --green: #4ade80;
  --star: #ffc442;
  --hot: #ff6b35;
}
```
**强制**：只用白/灰/金/红 + 热度橙，章节背景禁止彩色。

### 字号 / 留白
- body 15px / line-height 1.7
- 章节 `<h2>` 24px，章节之间 `margin: 72px 0 28px`
- 表格 13.5px，单元格 padding `12px 16px`
- container 最大宽度 1100px

### 10 章节结构（顺序固定）

1. **核心观点 hero** — 大标题 + 副标题金色强调 + 4 个数字卡（市场规模/龙头同比/国产化率/标的数）
2. **一 / 产业链结构图** — 上游→中游→下游 ▼ 箭头 4-5 层
3. **二 / 多路径挖掘概览** — 12 条路径命中统计 + 高/中/低置信标的数量
4. **三 / A 股标的池** — 按子分类分表，列：代码/股票/弹性★/现价/涨跌幅/流通市值/PE(TTM)/主力净流入/命中路径数/核心看点
5. **四 / 关键事件时间线** — 金色时间轴 4-7 条（新闻 + 博主动态混合）
6. **五 / 资金面全景** — 北向资金流向 + 融资余额趋势 + 龙虎榜机构动向
7. **六 / 市场情绪面** — 博主提及热度排名 + 观点摘要（来自 twitter cache）
8. **七 / 国产替代缺口** — 环节/现状/替代缺口/关键突破点
9. **八 / 核心投资逻辑** — 6 条带编号
10. **九 / 主要风险点** — 红点 list + 解禁预警
11. **附录 / 分层建议** — 赛道位置×弹性×资金认可度×路径命中数

### 星级评定标准（5 维度综合）

| 评级 | 条件 |
|---|---|
| ★★★ | 龙头 + 估值合理（PE < 行业均值）+ 资金流入 + 博主高频提及 + 命中路径 ≥3 |
| ★★☆ | 受益但非纯主营 / 估值偏高 / 资金中性 / 命中路径 2 条 |
| ★☆☆ | 纯题材 / 资金流出 / 无机构关注 / 仅 1 条路径命中 |

### 市场情绪面章节格式

```html
<h2>六 / 市场情绪面</h2>
<p class="meta">数据来源：X/Twitter stock 组 cache · 覆盖 16 位博主</p>

<table class="std">
  <tr><th>标的</th><th>提及次数</th><th>热度</th><th>博主观点摘要</th></tr>
  <tr><td>北方华创</td><td>7</td><td>🔥🔥🔥</td><td>多位博主看好设备龙头</td></tr>
</table>

<div class="quote-list">
  <div class="quote">
    <span class="author">每日快讯 (@dmjk001)</span>
    <span class="time">05-30 14:22</span>
    <p>PCB 板块涨停潮...</p>
  </div>
</div>
```

### 多路径挖掘概览章节格式

```html
<h2>二 / 多路径挖掘概览</h2>
<p class="meta">12 条路径并行挖掘 · 交叉验证置信度</p>

<div class="stats-row">
  <div class="stat-card"><span class="num high">12</span><span class="label">高置信标的</span></div>
  <div class="stat-card"><span class="num mid">8</span><span class="label">中置信标的</span></div>
  <div class="stat-card"><span class="num low">15</span><span class="label">低置信标的</span></div>
</div>

<table class="std">
  <tr><th>路径</th><th>命中数</th><th>独占标的</th><th>说明</th></tr>
  <tr><td>① 概念板块</td><td>18</td><td>2</td><td>同花顺/东财已打标</td></tr>
  <tr><td>② 主营业务</td><td>12</td><td>4</td><td>隐形标的挖掘</td></tr>
  <!-- ... -->
</table>
```

### 表格样式
```css
table.std td.stars { color: var(--star); letter-spacing: 1.5px; font-size: 12.5px; text-align: center; }
table.std td.stars .dim { color: rgba(255,196,66,0.18); }
.chg-up { color: var(--red); }
.chg-down { color: var(--green); }
.flow-in { color: var(--red); font-weight: 600; }
.flow-out { color: var(--green); }
.hot-3 { color: var(--hot); }
.high { color: var(--gold); }
.mid { color: var(--text-dim); }
.low { color: var(--text-mute); }
```

---

## 四、内容质量要求

### 必须包含
- 顶部 4 个关键数字卡
- 产业链结构图 ▼ 箭头 4-5 层
- 多路径挖掘概览（12 条路径命中统计）
- 每只个股：★ 评级 + PE + 主力净流入 + 命中路径数 + 核心看点（≤30 字，含硬数据）
- 资金面全景（北向/融资/龙虎榜三维）
- 市场情绪面（博主热度 + 观点摘要，来自 cache）
- 时间线 4-7 条
- 5-6 条投资逻辑 + 5-7 条风险点（含解禁预警）
- 附录分层建议

### 不要做
- ❌ 不要多色混用
- ❌ 段落里不要每个词都高亮，只保留 3-5 个关键数字
- ❌ HTML 末尾不要加 footer
- ❌ 不编造数据——所有数字必须来自实际 API 返回
- ❌ 东财端点必须走 em_get() 限流
- ❌ twitter 不要联网拉取，只读 cache
- ❌ 行情时间必须标注

---

## 五、常用 query 模板

### iwencai_query（产业链骨架 + 多路径挖掘）

| 维度 | query |
|---|---|
| 概念选股+估值 | `【主题】概念股 流通市值大于30亿 流通市值 PE(TTM) ROE 最近5日主力净流入 涨跌幅 按流通市值降序` |
| 细分环节 | `覆铜板概念股 流通市值 PE ROE 涨跌幅 按流通市值降序` |
| 龙头筛选 | `【主题】龙头 市值大于200亿 PE ROE 北向持股比例` |
| 主营业务挖掘 | `主营业务包含XX 或 主营业务包含YY 流通市值大于20亿 PE 涨跌幅 按流通市值降序` |
| 经营范围挖掘 | `经营范围包含XX 或 公司简介包含YY 流通市值大于20亿 PE 按流通市值降序` |
| ETF持仓 | `【主题】ETF 十大重仓股 流通市值 PE` |
| 机构调研 | `最近30天机构调研次数大于3次 属于【主题】概念 机构调研次数 流通市值 PE 按机构调研次数降序` |
| 参股关系 | `参股XX公司 或 子公司从事YY 流通市值 PE 涨跌幅` |
| 同行业对标 | `申万三级行业为XX 流通市值大于20亿 PE ROE 按流通市值降序` |

### iwencai_search（研报/新闻/公告）

| 维度 | query | channel |
|---|---|---|
| 研报 | `【主题】产业链 投资逻辑 2026` | report |
| 新闻 | `【主题】涨价 国产替代` | news |
| 公告-扩产 | `【主题】龙头 扩产 投资建设` | announcement |
| 公告-定增 | `【主题】定增 募集资金` | announcement |
| 公告-合作 | `【主题】战略合作 签署协议` | announcement |

---

## 六、输出
1. HTML 文件：`output/<topic-slug>_industry_chain.html`
2. `open <文件>` 浏览器打开
3. 简短总结：分层个股清单 + 关键数字 + 资金面结论 + 博主共识 + 风险提示 + 多路径命中统计

---

# INPUT · 本次输入（每次只改下面这块）

```yaml
产业链主题: <填入主题>
特殊关注:
  - <可选：特定环节/公司/逻辑>
twitter关键词: [关键词1, 关键词2, 关键词3] # 用于在 cache 中搜索
多路径关键词:  # 用于路径②③⑪的关键词扩展
  主营业务: [关键词A, 关键词B, 关键词C]
  经营范围: [关键词D, 关键词E]
  参股目标: [核心公司A, 核心公司B]
  同行业基准: [龙头A所在申万三级行业, 龙头B所在申万三级行业]
```
