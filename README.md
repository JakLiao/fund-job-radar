# Fund Job Radar · 融资-招聘信号监控工具

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

自动化监控融资信号，提前预判目标公司的招聘需求爆发时间点。
<img width="1869" height="1202" alt="image" src="https://github.com/user-attachments/assets/c5c319e3-d6a7-487b-b56e-22e55b717fb6" />

## 功能特性

- **数据采集**：TechCrunch RSS（免费，无需 API Key）
- **核心分析**：窗口期计算 + 机会评分（基于融资轮次/金额/时间窗口）
- **推送通知**：Server酱微信推送（支持每日摘要）
- **调度运行**：APScheduler，每 30 分钟抓取 TechCrunch，每天 09:00 推送摘要

## 安装

```bash
cd fund-job-radar
pip install -r requirements.txt
```

## 配置

编辑 `config.yaml`：

```yaml
notification:
  serverchan_sckey: "YOUR_SCKEY"  # 替换为你的 Server酱 SCKEY
  push_times: ["09:00"]           # 每日摘要推送时间
  quiet_hours_start: "22:00"       # 静默时段开始
  quiet_hours_end: "08:00"         # 静默时段结束

scoring:
  score_threshold: 5.0             # 低于此分数不推送

scheduler:
  techcrunch_interval_minutes: 30  # TechCrunch 抓取间隔
```

获取 Server酱 SCKEY：https://sct.ftqq.com/

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

- `funding_events` - 融资事件
- `opportunities` - 商机机会
- `job_postings` - 招聘信息（Phase 2）
- `company_aliases` - 公司名别名（用于消歧）

## 测试

```bash
cd fund-job-radar
python -m pytest tests/ -v
```

## 项目结构

```
fund-job-radar/
├── app/
│   ├── main.py              # 入口，APScheduler 调度
│   ├── config.py            # 配置加载
│   ├── database.py          # SQLite CRUD
│   ├── models.py            # 数据模型
│   ├── analyzer.py          # 窗口期 + 评分算法
│   ├── notifier.py          # Server酱推送
│   ├── scrapers/
│   │   ├── techcrunch.py    # TC RSS 抓取
│   │   ├── edgar.py         # SEC EDGAR（Phase 2）
│   │   ├── crunchbase.py    # Crunchbase API（Phase 2）
│   │   └── jobs.py          # 招聘数据（Phase 2）
│   └── utils/
│       └── fuzzy_match.py   # 公司名模糊匹配
├── data/                    # SQLite 数据库
├── tests/                   # 单元测试
├── config.yaml
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
score = round_weight × log10(amount_usd + 1) × window_days_remaining / 10
```

分数越高，机会越值得追。

## 永久分享链接格式

```
http://172.17.173.208:8484/fund_job_radar?sql=URL编码的SQL
```

## 一键直达链接

| 查询 | 链接 |
|------|------|
| 最新融资事件 | http://172.17.173.208:8484/fund_job_radar?sql=SELECT%20company_name%2C%20round_type%2C%20amount_usd%2C%20announcement_date%2C%20source%20FROM%20funding_events%20ORDER%20BY%20announcement_date%20DESC%20LIMIT%2020%3B |
| 高价值机会 | http://172.17.173.208:8484/fund_job_radar?sql=SELECT%20company_name%2C%20round_type%2C%20amount_usd%2C%20window_days_remaining%2C%20signal_strength%20FROM%20opportunities%20WHERE%20status%20%3D%20%27new%27%20ORDER%20BY%20amount_usd%20DESC%20LIMIT%2020%3B |
| 即将截止(<30天) | http://172.17.173.208:8484/fund_job_radar?sql=SELECT%20company_name%2C%20round_type%2C%20amount_usd%2C%20window_days_remaining%20FROM%20opportunities%20WHERE%20window_days_remaining%20%3C%2030%20AND%20status%20%3D%20%27new%27%20ORDER%20BY%20window_days_remaining%20ASC%3B |
| 窗口紧迫度一览 | http://172.17.173.208:8484/fund_job_radar?sql=SELECT%20company_name%2C%20round_type%2C%20amount_usd%2C%20window_days_remaining%2C%20CASE%20WHEN%20window_days_remaining%20%3C%3D%207%20THEN%20%27%F0%9F%94%B4%20%E7%B4%A7%E6%80%A5%27%20WHEN%20window_days_remaining%20%3C%3D%2014%20THEN%20%27%F0%9F%9F%A1%20%E4%B8%B4%E8%BF%91%27%20ELSE%20%27%F0%9F%9F%A2%20%E5%85%85%E8%B6%B3%27%20END%20AS%20urgency%20FROM%20opportunities%20WHERE%20status%20%3D%20%27new%27%20ORDER%20BY%20window_days_remaining%20ASC%3B |



### 最新融资事件（按日期倒序）
```sql
SELECT company_name, round_type, amount_usd, announcement_date, source
FROM funding_events
ORDER BY announcement_date DESC
LIMIT 20;
```

### 高价值机会（金额降序）
```sql
SELECT company_name, round_type, amount_usd, window_days_remaining, signal_strength
FROM opportunities
WHERE status = 'new'
ORDER BY amount_usd DESC
LIMIT 20;
```

### 即将截止的机会（窗口 < 30 天）
```sql
SELECT company_name, round_type, amount_usd, window_days_remaining, status
FROM opportunities
WHERE window_days_remaining < 30 AND status = 'new'
ORDER BY window_days_remaining ASC;
```

### 窗口期紧迫度一览
```sql
SELECT company_name, round_type, amount_usd, window_days_remaining,
       CASE
         WHEN window_days_remaining <= 7  THEN '🔴 紧急'
         WHEN window_days_remaining <= 14 THEN '🟡 临近'
         ELSE '🟢 充足'
       END AS urgency
FROM opportunities
WHERE status = 'new'
ORDER BY window_days_remaining ASC;
```

## License

MIT
