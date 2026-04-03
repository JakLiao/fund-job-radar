# Fund-Job Radar · 融资-招聘信号监控工具

**版本：** v1.3.0
**作者：** 商觅 + 码灵
**日期：** 2026-04-02

---

## 1. 背景与目标

**核心逻辑：** 融资消息（"将来式"）→ 招聘爆发（"过去式"），两者之间存在可量化的窗口期，是最佳商机切入点。

**目标：** 构建自动化监控工具，在融资信号出现后，提前预判目标公司的招聘需求爆发时间点，并推送给用户。

---

## 2. 系统架构

```
数据采集层（Data Sources）
│
├── TechCrunch RSS Feed        [免费, 无需API-key]
├── SEC EDGAR Form D          [免费, 无需API-key, 美国股权融资, USD→CNY]
├── 中国融资数据               [36kr RSS / 投资界 / 创业邦, CNY]
├── Crunchbase API            [免费额度: 100req/day, USD→CNY]
└── 公司官网 / 招聘页          [Playwright 动态抓取, Greenhouse API]

        ↓

分析引擎（Analysis Engine）
│
├── 公司名称消歧（fuzzy match）
├── 行业分类（行业知识库 + 关键词匹配）
├── 融资事件去重（公司+轮次+来源 三键）
├── 窗口期计算（基于融资轮次）
└── 机会评分（round_type权重 × log10(CNY/7.2+1) × 窗口天数 / 10）

        ↓

存储层（Storage）
│
└── SQLite（fund_job_radar.db）
    ├── funding_events 表     （融资事件）
    ├── job_postings 表      （招聘信息）
    └── opportunities 表     （商机）

        ↓

推送层（Notification）
│
└── 飞书群机器人             [Webhook 推送]

        ↓

调度层（Scheduler）
│
└── APScheduler
    ├── TechCrunch RSS: 每30分钟
    ├── EDGAR Form D: 每6小时
    ├── 中国融资数据: 每30分钟
    ├── Greenhouse: 每6小时
    └── 公司官网招聘页: 每12小时（Playwright）
```

---

## 3. 数据模型

### 3.1 funding_events（融资事件）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PRIMARY KEY | UUID |
| company_name | TEXT | 公司名称 |
| company_domain | TEXT | 官网域名（用于关联招聘） |
| round_type | TEXT | Seed/A/B/C/D/Angel/Pre-A/Pre-B/Pre-IPO |
| amount_usd | REAL | **融资金额（人民币元，CNY）**，统一存储 |
| announcement_date | DATETIME | 公布日期 |
| investors | TEXT | 投资方（逗号分隔） |
| source_url | TEXT | 来源链接 |
| source | TEXT | tc / edgar / cn / crunchbase |
| industry_group | TEXT | 行业分类（AI/医疗/机器人等） |
| created_at | DATETIME | 记录创建时间 |

### 3.2 job_postings（招聘信息）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PRIMARY KEY | UUID |
| company_name | TEXT | 公司名称 |
| job_title | TEXT | 职位名称 |
| job_count | INTEGER | 该公司同期招聘职位数 |
| posting_date | DATETIME | 发布日期 |
| source | TEXT | greenhouse / careers |
| created_at | DATETIME | 记录创建时间 |

### 3.3 opportunities（商机）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PRIMARY KEY | UUID |
| company_name | TEXT | 公司名称 |
| funding_event_id | TEXT FK | 关联融资事件（可为 NULL，若关联事件已删除） |
| signal_strength | TEXT | HIGH / MEDIUM / LOW |
| window_days_remaining | INTEGER | 窗口剩余天数（估算） |
| recommended_action | TEXT | 推荐动作描述 |
| status | TEXT | new / sent / archived |
| created_at | DATETIME | 记录创建时间 |

---

## 4. 核心算法

### 4.1 窗口期估算

| 融资轮次 | 典型延迟 | 窗口长度 | 评分权重 |
|---|---|---|---|
| Seed | 2-4周 | **45天** | ×1.0 |
| Series A | 1-3个月 | **90天** | ×2.0 |
| Series B | 2-4个月 | **120天** | ×3.0 |
| Series C+ | 3-6个月 | **180天** | ×4.0 |

> 阈值可通过 `config.yaml` 的 `scoring` 节点配置。

### 4.2 机会评分公式

```
score = round_type_weight × log10(amount_cny / 7.2 + 1) × window_days_remaining / 10
```

- `amount_cny` 为人民币元（统一存储单位）
- `/7.2` 将 CNY 归一化为 USD 等效值，保证评分与国际数据一致
- `log10` 压缩金额量级，避免大金额主导评分

### 4.3 融资事件去重

去重键：**公司名称 + 轮次 + 来源**

```sql
SELECT id FROM funding_events
WHERE company_name = ? AND round_type = ? AND source = ?
```

- 不使用 `announcement_date` 去重，因为部分爬虫（如 pedaily/cyzone）使用 `datetime.now()` 当日期，每次运行都不同

### 4.4 公司名称消歧

- 用 `rapidfuzz` 做 fuzzy match
- 阈值：>85分视为同一公司
- 维护一张知识库：`scripts/cn_industry_classifier.py`（中国公司行业分类）

---

## 5. 数据采集规格

### 5.1 TechCrunch RSS
- 源：`https://techcrunch.com/feed/`
- 解析：公司名、轮次、金额（USD）、日期
- 过滤：排除并购、IPO、增发等非融资事件

### 5.2 SEC EDGAR Form D
- 端点：`https://data.sec.gov/submissions/CIK{cik}.json`
- 解析：公司名、申报日期、融资金额上限（XML）
- 金额：USD → CNY（×7.2）统一存储
- 过滤：仅保留融资金额 ≥ 180万元（≈$25k USD）

### 5.3 中国融资数据
- **36kr RSS**：`https://36kr.com/feed` — 最可靠
- **投资界**：`https://www.pedaily.cn/first/t76/` — Playwright 渲染
- **创业邦**：`https://www.cyzone.cn/event/` — HTML 解析
- 金额：直接存 CNY（无转换）
- 行业分类：知识库匹配（`cn_industry_classifier.py`）

### 5.4 公司招聘数据
- **Greenhouse**：76+ 科技公司招聘板，公开 API
- **公司官网**：Playwright 探测 `/careers`、`/jobs`、`/about/careers` 等路径

---

## 6. 推送规格

### 6.1 飞书群机器人
- 配置：用户填入飞书 Webhook URL
- 推送格式（金额展示为中文单位）：
  ```
  🔔 融资信号捕获
  公司：XXX
  轮次：Series B | 金额：¥5.0千万元
  窗口剩余：约90天
  推荐动作：立即联系猎头/投递简历
  来源：CN（36kr）
  ```

### 6.2 推送规则
- 新融资事件：实时（<5分钟内）
- 每日摘要：可选，用户配置时间（如 09:00）
- 静默时段：可配置（如 22:00-08:00）

---

## 7. 配置文件（config.yaml）

```yaml
notification:
  feishu_webhook: "YOUR_FEISHU_WEBHOOK"  # 飞书群机器人
  push_times: ["09:00"]
  quiet_hours_start: "22:00"
  quiet_hours_end: "08:00"

edgar:
  enabled: true              # 启用 EDGAR 数据源
  days_lookback: 60         # 抓取最近 60 天数据
  min_amount: 1800000       # 最低融资金额（人民币元），$25万×7.2≈180万元

scoring:
  window_seed_days: 45
  window_series_a_days: 90
  window_series_b_days: 120
  window_series_c_plus_days: 180
  score_threshold: 5.0       # 低于此分数不推送
  signal_high_threshold: 15.0  # HIGH 信号阈值（可配置）
  signal_medium_threshold: 8.0 # MEDIUM 信号阈值（可配置）

scheduler:
  techcrunch_interval_minutes: 30  # TechCrunch RSS
  edgar_interval_hours: 6          # SEC EDGAR
  cn_funding_interval_minutes: 30   # 中国融资数据

database:
  path: "data/fund_job_radar.db"
```

---

## 8. 目录结构

```
fund-job-radar/
├── SPEC.md
├── config.yaml
├── requirements.txt
├── README.md
├── LICENSE（MIT）
├── app/
│   ├── __init__.py
│   ├── main.py              # 入口，APScheduler 调度
│   ├── config.py            # 配置加载（线程安全单例）
│   ├── database.py          # SQLite 初始化 + CRUD
│   ├── models.py            # 数据模型（dataclass）
│   ├── web.py               # Flask Web 界面
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── techcrunch.py    # TC RSS 抓取
│   │   ├── edgar.py         # SEC EDGAR 抓取（金额 USD→CNY）
│   │   ├── cn_funding.py    # 中国融资数据（36kr/pedaily/cyzone）
│   │   ├── crunchbase.py    # Crunchbase API
│   │   └── jobs.py          # 招聘数据（Greenhouse + Playwright）
│   ├── analyzer.py          # 关联分析 + 评分
│   ├── notifier.py          # 飞书推送
│   └── utils/
│       ├── __init__.py
│       ├── fuzzy_match.py    # 公司名消歧
│       └── date_parser.py    # 共享日期解析工具
├── scripts/
│   └── cn_industry_classifier.py  # 中国公司行业分类知识库
├── data/
│   └── fund_job_radar.db    # SQLite 数据库
└── tests/
    ├── __init__.py
    ├── test_techcrunch.py
    ├── test_analyzer.py
    ├── test_fuzzy_match.py
    ├── test_cn_funding.py   # 中国金额解析 + 轮次分类
    ├── test_jobs.py         # 公司名清洗 + 中国公司判断
    ├── test_notifier.py      # 金额格式化（CNY）
    ├── test_config.py        # 配置项测试
    └── test_date_parser.py  # 日期解析工具测试
```

---

## 9. 实现进度

### Phase 1（MVP）
- [x] TechCrunch RSS 抓取 → 解析 → 入库
- [x] 分析引擎：窗口期计算 + 机会评分
- [x] 飞书推送
- [x] config.yaml 配置
- [x] 每日摘要推送

### Phase 2（数据丰富）
- [x] SEC EDGAR Form D 抓取
  - 免费数据源，覆盖美国私募融资（USD→CNY 统一存储）
  - 每 6 小时自动抓取
  - 支持 Form D / D/A / C
- [x] 中国融资数据
  - 36kr RSS（最可靠）
  - 投资界（需 Playwright）
  - 创业邦（HTML 解析）
  - 金额直接存 CNY
  - 行业分类知识库
- [x] Greenhouse 招聘板
  - 76+ 科技公司招聘板自动匹配
  - 公开 API，无需登录
  - 每 6 小时自动抓取
- [x] 公司官网招聘页（Playwright）
  - 使用 PlaywrightContext 上下文管理器统一生命周期
  - 自动探测 /careers, /jobs 等路径

### Phase 3（产品化）
- [x] Web 界面（Flask）— 融资事件分页 + 动态下拉筛选
- [x] 历史数据可视化（Datasette，端口 8484）

---

## 10. 验收标准

1. 运行 `python -m app.main`，无报错，调度器正常启动
2. 各数据源在配置间隔内抓取到测试数据并入库（无重复）
3. 新融资事件触发飞书推送，消息格式正确（金额显示为 ¥千万元/亿元）
4. `data/fund_job_radar.db` 包含 funding_events、opportunities 表
5. 单元测试：`pytest tests/` 全部通过
6. Web 界面正常加载，融资事件表格支持分页和筛选（来源/轮次/行业动态筛选）
