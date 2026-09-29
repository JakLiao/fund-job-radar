# Fund Job Radar · 融资-招聘信号监控工具

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

自动化监控融资信号，提前预判目标公司的招聘需求爆发时间点。
<img width="1869" height="1202" alt="image" src="https://github.com/user-attachments/assets/c5c319e3-d6a7-487b-b56e-22e55b717fb6" />

## 功能特性

- **数据采集**：TechCrunch RSS（免费）、SEC EDGAR Form D（免费）、中文融资源（pedaily / 36kr / 创业邦）
- **核心分析**：窗口期计算 + 机会评分（基于融资轮次/金额/时间窗口）
- **推送通知**：飞书群机器人 Webhook（支持每日摘要）
- **招聘监控**：独立分批 worker 抓取目标公司 careers 页，避免长任务阻塞调度
- **调度运行**：APScheduler 主进程（TechCrunch 30 分钟 / EDGAR 6 小时）+ PM2 cron 招聘 worker

## 安装

```bash
cd fund-job-radar
pip install -r requirements.txt
```

## 配置

编辑 `config.yaml`：

```yaml
notification:
  # 飞书群机器人 Webhook，从环境变量 FEISHU_WEBHOOK 读取（不要在 yaml 中填明文）
  feishu_webhook: "${FEISHU_WEBHOOK}"
  push_times: ["09:00"]           # 每日摘要推送时间
  quiet_hours_start: "22:00"       # 静默时段开始
  quiet_hours_end: "08:00"         # 静默时段结束

apis:
  crunchbase_key: ""               # 可选，留空则跳过 Crunchbase

scoring:
  score_threshold: 5.0             # 低于此分数不推送

scheduler:
  techcrunch_interval_minutes: 30  # TechCrunch 抓取间隔
  edgar_interval_hours: 6          # EDGAR 抓取间隔
```

### 配置推送 Webhook

Webhook 值**不要写进 `config.yaml`**，通过环境变量提供：

1. 复制模板：`cp .env.example .env`
2. 获取 Webhook：飞书群 → 群设置 → 群机器人 → 添加机器人 → 复制 Webhook 地址
3. 填入 `.env`：

```
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/你的真实值
```

`.env` 已被 `.gitignore` 忽略，不会进入版本库。

> **注意**：Python 不会自动加载 `.env`。直接 `python app/main.py` 运行时需先 `export $(grep -v '^#' .env | xargs)`；使用 PM2 托管时，[ecosystem.config.cjs](file:///mnt/e/code/fund-job-radar/ecosystem.config.cjs) 会自动读取 `.env` 并注入。

可用以下命令自检配置是否生效：

```bash
python -c "from app.config import get_config; print(get_config().validate_notification_config())"
```

输出空字符串表示校验通过；若输出告警文本，说明 `FEISHU_WEBHOOK` 未被正确读取，所有通知会被静默丢弃。

## 运行

```bash
python app/main.py
```

程序将：
1. 初始化 SQLite 数据库（`data/fund_job_radar.db`）
2. 立即抓取一次 TechCrunch RSS
3. 启动调度器（30 分钟抓取 + 每日摘要）

## 数据库

数据存储在 `data/fund_job_radar.db`，包含：

- `funding_events` - 融资事件（金额列名为 `amount_cny`，人民币元）
- `opportunities` - 商机机会（**不含金额列**，金额需 JOIN `funding_events` 获取）
- `job_postings` - 招聘信息
- `company_aliases` - 公司名别名（用于消歧）

> 金额统一以人民币存储（`amount_cny`），TechCrunch 的美元金额在抓取时即按汇率换算。

## 测试

```bash
cd fund-job-radar
python -m pytest tests/ -v
```

## 项目结构

```
fund-job-radar/
├── app/
│   ├── main.py              # 主进程入口，APScheduler 调度
│   ├── job_worker.py        # 招聘抓取分批 worker（独立进程，PM2 cron 拉起）
│   ├── config.py            # 配置加载（含 ${ENV} 解析与 webhook 校验）
│   ├── database.py          # SQLite CRUD
│   ├── models.py            # 数据模型
│   ├── analyzer.py          # 窗口期 + 评分算法
│   ├── notifier.py          # 飞书推送
│   ├── web.py               # Web 仪表盘
│   ├── scrapers/
│   │   ├── techcrunch.py    # TechCrunch RSS 抓取
│   │   ├── edgar.py         # SEC EDGAR Form D 抓取
│   │   ├── cn_funding.py    # 中文融资源抓取
│   │   ├── crunchbase.py    # Crunchbase API（需 API Key）
│   │   └── jobs.py          # 招聘数据抓取
│   └── utils/
│       ├── fuzzy_match.py   # 公司名模糊匹配
│       └── date_parser.py   # 日期解析
├── data/                    # SQLite 数据库（git 忽略）
├── scripts/                 # 一次性数据迁移脚本
├── tests/                   # 单元测试
├── .env                     # 飞书 Webhook 等敏感配置（git 忽略，勿提交）
├── .env.example             # 配置模板
├── config.yaml
├── ecosystem.config.cjs     # PM2 主进程配置
├── ecosystem.jobs.config.cjs # PM2 招聘 worker 进程池配置
├── requirements.txt
└── README.md
```

## 算法说明

### 窗口期估算

| 轮次 | 窗口长度 |
|------|----------|
| Seed | ~14 天 |
| Series A | ~45 天 |
| Series B | ~60 天 |
| Series C+ | ~90 天 |

### 机会评分公式

```
score = round_weight × log10(amount_cny / 7.2 + 1) × window_days_remaining / 10
```

其中 `round_weight` 按轮次取值：Seed 1.0 / A 2.0 / B 3.0 / C 4.0 / D 4.5 / E 及以后 5.0。金额先除以 7.2 折算为美元等值再取对数，使评分与币种无关。分数越高，机会越值得追。

## 永久分享链接格式

```
http://172.17.173.208:8484/fund_job_radar?sql=URL编码的SQL
```

## 一键直达链接

| 查询 | 链接 |
|------|------|
| 最新融资事件 | http://172.17.173.208:8484/fund_job_radar?sql=SELECT%20company_name%2C%20round_type%2C%20amount_cny%2C%20announcement_date%2C%20source%20FROM%20funding_events%20ORDER%20BY%20announcement_date%20DESC%20LIMIT%2020%3B |
| 高价值机会 | http://172.17.173.208:8484/fund_job_radar?sql=SELECT%20o.company_name%2C%20f.round_type%2C%20f.amount_cny%2C%20o.window_days_remaining%2C%20o.signal_strength%20FROM%20opportunities%20o%20JOIN%20funding_events%20f%20ON%20f.id%20%3D%20o.funding_event_id%20WHERE%20o.status%20%3D%20%27new%27%20ORDER%20BY%20f.amount_cny%20DESC%20LIMIT%2020%3B |
| 即将截止(<30天) | http://172.17.173.208:8484/fund_job_radar?sql=SELECT%20o.company_name%2C%20f.round_type%2C%20f.amount_cny%2C%20o.window_days_remaining%20FROM%20opportunities%20o%20JOIN%20funding_events%20f%20ON%20f.id%20%3D%20o.funding_event_id%20WHERE%20o.window_days_remaining%20%3C%2030%20AND%20o.status%20%3D%20%27new%27%20ORDER%20BY%20o.window_days_remaining%20ASC%3B |
| 窗口紧迫度一览 | http://172.17.173.208:8484/fund_job_radar?sql=SELECT%20o.company_name%2C%20f.round_type%2C%20f.amount_cny%2C%20o.window_days_remaining%2C%20CASE%20WHEN%20o.window_days_remaining%20%3C%3D%207%20THEN%20%27%F0%9F%94%B4%20%E7%B4%A7%E6%80%A5%27%20WHEN%20o.window_days_remaining%20%3C%3D%2014%20THEN%20%27%F0%9F%9F%A1%20%E4%B8%B4%E8%BF%91%27%20ELSE%20%27%F0%9F%9F%A2%20%E5%85%85%E8%B6%B3%27%20END%20AS%20urgency%20FROM%20opportunities%20o%20JOIN%20funding_events%20f%20ON%20f.id%20%3D%20o.funding_event_id%20WHERE%20o.status%20%3D%20%27new%27%20ORDER%20BY%20o.window_days_remaining%20ASC%3B |



### 最新融资事件（按日期倒序）
```sql
SELECT company_name, round_type, amount_cny, announcement_date, source
FROM funding_events
ORDER BY announcement_date DESC
LIMIT 20;
```

### 高价值机会（金额降序）
> `opportunities` 表不含金额列，需 JOIN `funding_events` 获取。

```sql
SELECT o.company_name, f.round_type, f.amount_cny, o.window_days_remaining, o.signal_strength
FROM opportunities o
JOIN funding_events f ON f.id = o.funding_event_id
WHERE o.status = 'new'
ORDER BY f.amount_cny DESC
LIMIT 20;
```

### 即将截止的机会（窗口 < 30 天）
```sql
SELECT o.company_name, f.round_type, f.amount_cny, o.window_days_remaining, o.status
FROM opportunities o
JOIN funding_events f ON f.id = o.funding_event_id
WHERE o.window_days_remaining < 30 AND o.status = 'new'
ORDER BY o.window_days_remaining ASC;
```

### 窗口期紧迫度一览
```sql
SELECT o.company_name, f.round_type, f.amount_cny, o.window_days_remaining,
       CASE
         WHEN o.window_days_remaining <= 7  THEN '🔴 紧急'
         WHEN o.window_days_remaining <= 14 THEN '🟡 临近'
         ELSE '🟢 充足'
       END AS urgency
FROM opportunities o
JOIN funding_events f ON f.id = o.funding_event_id
WHERE o.status = 'new'
ORDER BY o.window_days_remaining ASC;
```

## License

MIT
