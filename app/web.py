"""Web Dashboard for Fund Job Radar.

简单的 Web 界面查看融资事件历史和搜索。
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

# Database path
DB_PATH = Path(__file__).parent.parent / "data" / "fund_job_radar.db"


def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def format_amount(amount):
    """Format amount for display (amount stored in CNY yuan)."""
    if amount >= 100_000_000:  # ≥1亿元
        return f"¥{amount/100_000_000:.1f}亿元"
    elif amount >= 10_000_000:  # ≥1千万
        return f"¥{amount/10_000_000:.1f}千万元"
    elif amount >= 1_000_000:  # ≥1百万
        return f"¥{amount/1_000_000:.1f}百万元"
    elif amount >= 10_000:  # ≥1万
        return f"¥{amount/10_000:.1f}万元"
    elif amount == 0:
        return "未披露"
    else:
        return f"¥{amount:,.0f}元"


def get_funding_events(search=None, source=None, round_type=None, industry=None, page=1, per_page=20):
    """Get funding events from database with pagination and filtering.

    Returns (events, total_count, total_pages).
    """
    conn = get_db_connection()
    offset = (page - 1) * per_page

    # Build filtered WHERE clause (reused for count and data query)
    conditions = []
    params = []
    if search:
        conditions.append("(company_name LIKE ? OR round_type LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    if source:
        conditions.append("source = ?")
        params.append(source)
    if round_type:
        conditions.append("round_type = ?")
        params.append(round_type)
    if industry:
        conditions.append("industry_group = ?")
        params.append(industry)
    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Total count (unfiltered by limit/offset)
    total = conn.execute(f"SELECT COUNT(*) FROM funding_events WHERE {where_clause}", params).fetchone()[0]
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    # Paginated data
    data_params = params + [per_page, offset]
    rows = conn.execute(
        f"SELECT * FROM funding_events WHERE {where_clause} ORDER BY announcement_date DESC LIMIT ? OFFSET ?",
        data_params,
    ).fetchall()
    conn.close()

    return [dict(row) for row in rows], total, total_pages


def get_filter_options():
    """Return dynamic filter options from database (for dropdown menus)."""
    conn = get_db_connection()
    sources = [r[0] for r in conn.execute("SELECT DISTINCT source FROM funding_events ORDER BY source").fetchall()]
    rounds = [r[0] for r in conn.execute("SELECT DISTINCT round_type FROM funding_events WHERE round_type IS NOT NULL AND round_type != '' ORDER BY round_type").fetchall()]
    industries = [r[0] for r in conn.execute("SELECT DISTINCT industry_group FROM funding_events WHERE industry_group IS NOT NULL AND industry_group != '' ORDER BY industry_group").fetchall()]
    conn.close()
    return sources, rounds, industries


def get_opportunities(status=None, limit=50):
    """Get opportunities from database."""
    conn = get_db_connection()
    
    # Use LEFT JOIN to avoid dropping opportunities whose funding_event
    # was deleted (orphaned rows). When f.id is NULL, fall back to
    # o.company_name stored in the opportunity itself.
    query = """
        SELECT
            o.*,
            COALESCE(f.company_name, o.company_name) AS company_name,
            f.round_type,
            f.amount_cny,
            f.announcement_date,
            f.source
        FROM opportunities o
        LEFT JOIN funding_events f ON o.funding_event_id = f.id
        WHERE 1=1
    """
    params = []
    
    if status:
        query += " AND o.status = ?"
        params.append(status)
    
    query += " ORDER BY o.window_days_remaining ASC LIMIT ?"
    params.append(limit)
    
    opps = conn.execute(query, params).fetchall()
    conn.close()
    
    return [dict(row) for row in opps]


@app.route("/")
def index():
    """Main dashboard page."""
    search = request.args.get("search", "")
    source_filter = request.args.get("source", "")
    round_filter = request.args.get("round", "")
    industry_filter = request.args.get("industry", "")
    page = max(1, int(request.args.get("page", 1)))

    events, total, total_pages = get_funding_events(
        search=search, source=source_filter,
        round_type=round_filter if round_filter else None,
        industry=industry_filter if industry_filter else None,
        page=page, per_page=20,
    )

    # Format for display
    for event in events:
        event["amount_formatted"] = format_amount(event["amount_cny"])
        event["date_formatted"] = datetime.fromisoformat(event["announcement_date"]).strftime("%Y-%m-%d")
        event["source_icon"] = "🔵" if event["source"] == "tc" else "🟢"

    # Dynamic filter options
    sources, rounds, industries = get_filter_options()

    # Stats
    conn = get_db_connection()
    stats = {
        "total_events": conn.execute("SELECT COUNT(*) FROM funding_events").fetchone()[0],
        "tc_events": conn.execute("SELECT COUNT(*) FROM funding_events WHERE source='tc'").fetchone()[0],
        "edgar_events": conn.execute("SELECT COUNT(*) FROM funding_events WHERE source='edgar'").fetchone()[0],
        "cn_events": conn.execute("SELECT COUNT(*) FROM funding_events WHERE source='cn'").fetchone()[0],
        "total_opportunities": conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0],
        "pending_opportunities": conn.execute("SELECT COUNT(*) FROM opportunities WHERE status='new'").fetchone()[0],
    }
    conn.close()

    return render_template_string(
        TEMPLATE,
        events=events, stats=stats,
        search=search, source_filter=source_filter,
        round_filter=round_filter, industry_filter=industry_filter,
        page=page, total_pages=total_pages, total=total,
        sources=sources, rounds=rounds, industries=industries,
    )


@app.route("/opportunities")
def opportunities():
    """Opportunities page."""
    status = request.args.get("status", "")
    
    opps = get_opportunities(status=status if status else None)
    
    # Format for display
    for opp in opps:
        opp["amount_formatted"] = format_amount(opp["amount_cny"])
        opp["date_formatted"] = datetime.fromisoformat(opp["announcement_date"]).strftime("%Y-%m-%d")
        opp["source_icon"] = "🔵" if opp["source"] == "tc" else "🟢"
    
    return render_template_string(OPPORTUNITIES_TEMPLATE, opportunities=opps, status=status)


@app.route("/api/events")
def api_events():
    """API endpoint for funding events."""
    search = request.args.get("search", "")
    source = request.args.get("source", "")
    
    events = get_funding_events(search=search, source=source if source else None)
    
    for event in events:
        event["amount_formatted"] = format_amount(event["amount_cny"])
        event["date_formatted"] = datetime.fromisoformat(event["announcement_date"]).strftime("%Y-%m-%d")
    
    return jsonify({"events": events})


@app.route("/api/stats")
def api_stats():
    """API endpoint for statistics."""
    conn = get_db_connection()
    stats = {
        "total_events": conn.execute("SELECT COUNT(*) FROM funding_events").fetchone()[0],
        "tc_events": conn.execute("SELECT COUNT(*) FROM funding_events WHERE source='tc'").fetchone()[0],
        "edgar_events": conn.execute("SELECT COUNT(*) FROM funding_events WHERE source='edgar'").fetchone()[0],
        "total_opportunities": conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0],
        "pending": conn.execute("SELECT COUNT(*) FROM opportunities WHERE status='new'").fetchone()[0],
    }
    conn.close()
    return jsonify(stats)


# HTML Templates
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fund Job Radar · 融资监控</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #333; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        h1 { color: #1a1a1a; margin-bottom: 20px; }
        
        /* Stats Cards */
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 30px; }
        .stat-card { background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .stat-value { font-size: 28px; font-weight: bold; color: #2563eb; }
        .stat-label { color: #666; font-size: 14px; margin-top: 5px; }
        
        /* Search */
        .search-bar { background: white; border-radius: 8px; padding: 15px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .search-bar form { display: flex; gap: 10px; flex-wrap: wrap; }
        .search-bar input { flex: 1; min-width: 200px; padding: 10px 15px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }
        .search-bar select { padding: 10px 15px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }
        .search-bar button { padding: 10px 20px; background: #2563eb; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
        .search-bar button:hover { background: #1d4ed8; }
        
        /* Table */
        .table-container { background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden; }
        table { width: 100%; border-collapse: collapse; }
        th { background: #f8fafc; padding: 12px 15px; text-align: left; font-weight: 600; border-bottom: 2px solid #e2e8f0; }
        td { padding: 12px 15px; border-bottom: 1px solid #e2e8f0; }
        tr:hover { background: #f8fafc; }
        .source-icon { font-size: 18px; }
        .amount { font-weight: 600; color: #059669; }
        .date { color: #64748b; font-size: 14px; }
        .round { display: inline-block; padding: 2px 8px; background: #dbeafe; color: #1e40af; border-radius: 4px; font-size: 12px; }
        .industry { display: inline-block; padding: 2px 8px; background: #f3e8ff; color: #7c3aed; border-radius: 4px; font-size: 11px; margin-top: 4px; }
        
        /* Nav */
        .nav { display: flex; gap: 20px; margin-bottom: 20px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px; }
        .nav a { color: #64748b; text-decoration: none; padding: 8px 16px; border-radius: 6px; }
        .nav a:hover { background: #f1f5f9; }
        .nav a.active { color: #2563eb; background: #dbeafe; font-weight: 500; }
        
        .empty { text-align: center; padding: 40px; color: #64748b; }

        /* Pagination */
        .pagination { display: flex; gap: 6px; justify-content: center; align-items: center; margin-top: 20px; flex-wrap: wrap; }
        .pagination a, .pagination span { display: inline-block; padding: 6px 12px; border-radius: 6px; text-decoration: none; font-size: 14px; }
        .pagination a { background: white; color: #2563eb; border: 1px solid #d1d5db; }
        .pagination a:hover { background: #eff6ff; }
        .pagination .current { background: #2563eb; color: white; border: 1px solid #2563eb; font-weight: 600; }
        .pagination span { color: #9ca3af; border: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Fund Job Radar</h1>
        
        <nav class="nav">
            <a href="/" class="active">融资事件</a>
            <a href="/opportunities">商机</a>
        </nav>
        
        <!-- Stats -->
        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">{{ stats.total_events }}</div>
                <div class="stat-label">总融资事件</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.tc_events }}</div>
                <div class="stat-label">TechCrunch</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.edgar_events }}</div>
                <div class="stat-label">EDGAR</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.cn_events }}</div>
                <div class="stat-label">中国源</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.total_opportunities }}</div>
                <div class="stat-label">总商机</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.pending_opportunities }}</div>
                <div class="stat-label">待处理</div>
            </div>
        </div>
        
        <!-- Search -->
        <div class="search-bar">
            <form method="get" style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;">
                <input type="text" name="search" placeholder="搜索公司名..." value="{{ search }}" style="flex:0 0 180px;">
                <select name="source">
                    <option value="">全部来源</option>
                    {% for s in sources %}
                    <option value="{{ s }}" {% if source_filter == s %}selected{% endif %}>{{ s|upper }}</option>
                    {% endfor %}
                </select>
                <select name="round">
                    <option value="">全部轮次</option>
                    {% for r in rounds %}
                    <option value="{{ r }}" {% if round_filter == r %}selected{% endif %}>{{ r }}</option>
                    {% endfor %}
                </select>
                <select name="industry">
                    <option value="">全部行业</option>
                    {% for i in industries %}
                    <option value="{{ i }}" {% if industry_filter == i %}selected{% endif %}>{{ i }}</option>
                    {% endfor %}
                </select>
                <button type="submit">🔍 搜索</button>
                {% if search or source_filter or round_filter or industry_filter %}
                <a href="/" style="padding:10px 16px;background:#e5e7eb;color:#374151;border-radius:6px;text-decoration:none;font-size:14px;">重置</a>
                {% endif %}
            </form>
        </div>

        <!-- Pagination info -->
        {% if total_pages > 1 %}
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;color:#64748b;font-size:14px;">
            <span>共 {{ total }} 条，第 {{ page }}/{{ total_pages }} 页</span>
        </div>
        {% endif %}

        <!-- Table -->
        <div class="table-container">
            {% if events %}
            <table>
                <thead>
                    <tr>
                        <th>来源</th>
                        <th>公司</th>
                        <th>轮次</th>
                        <th>金额</th>
                        <th>日期</th>
                        <th>链接</th>
                    </tr>
                </thead>
                <tbody>
                    {% for event in events %}
                    <tr>
                        <td><span class="source-icon">{{ event.source_icon }} {{ event.source|upper }}</span></td>
                        <td>
                            <strong>{{ event.company_name }}</strong>
                            {% if event.industry_group %}
                            <br><span class="industry">{{ event.industry_group }}</span>
                            {% endif %}
                        </td>
                        <td><span class="round">{{ event.round_type }}</span></td>
                        <td class="amount">{{ event.amount_formatted }}</td>
                        <td class="date">{{ event.date_formatted }}</td>
                        <td><a href="{{ event.source_url }}" target="_blank">查看</a></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="empty">暂无数据</div>
            {% endif %}
        </div>

        <!-- Pagination controls -->
        {% if total_pages > 1 %}
        <div class="pagination">
            {% if page > 1 %}
            <a href="?page={{ page - 1 }}&search={{ search }}&source={{ source_filter }}&round={{ round_filter }}&industry={{ industry_filter }}">← 上一页</a>
            {% endif %}
            {% for p in range(1, total_pages + 1) %}
                {% if p == page %}
                <span class="current">{{ p }}</span>
                {% elif p <= 3 or p >= total_pages - 1 or (p >= page - 1 and p <= page + 1) %}
                <a href="?page={{ p }}&search={{ search }}&source={{ source_filter }}&round={{ round_filter }}&industry={{ industry_filter }}">{{ p }}</a>
                {% elif p == 4 or p == total_pages - 2 %}
                <span>...</span>
                {% endif %}
            {% endfor %}
            {% if page < total_pages %}
            <a href="?page={{ page + 1 }}&search={{ search }}&source={{ source_filter }}&round={{ round_filter }}&industry={{ industry_filter }}">下一页 →</a>
            {% endif %}
        </div>
        {% endif %}
    </div>
</body>
</html>
"""

OPPORTUNITIES_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>商机 · Fund Job Radar</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #333; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        h1 { color: #1a1a1a; margin-bottom: 20px; }
        
        .nav { display: flex; gap: 20px; margin-bottom: 20px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px; }
        .nav a { color: #64748b; text-decoration: none; padding: 8px 16px; border-radius: 6px; }
        .nav a:hover { background: #f1f5f9; }
        .nav a.active { color: #2563eb; background: #dbeafe; font-weight: 500; }
        
        .table-container { background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden; }
        table { width: 100%; border-collapse: collapse; }
        th { background: #f8fafc; padding: 12px 15px; text-align: left; font-weight: 600; border-bottom: 2px solid #e2e8f0; }
        td { padding: 12px 15px; border-bottom: 1px solid #e2e8f0; }
        tr:hover { background: #f8fafc; }
        
        .strength { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
        .strength.high { background: #dcfce7; color: #166534; }
        .strength.medium { background: #fef9c3; color: #854d0e; }
        .strength.low { background: #fee2e2; color: #991b1b; }
        
        .window { font-weight: 600; }
        .window.urgent { color: #dc2626; }
        .window.warning { color: #f59e0b; }
        .window.ok { color: #16a34a; }
        
        .status { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
        .status.new { background: #dbeafe; color: #1e40af; }
        .status.sent { background: #d1fae5; color: #065f46; }
        .status.archived { background: #f3f4f6; color: #6b7280; }
    </style>
</head>
<body>
    <div class="container">
        <h1>💼 商机列表</h1>
        
        <nav class="nav">
            <a href="/">融资事件</a>
            <a href="/opportunities" class="active">商机</a>
        </nav>
        
        <div class="table-container">
            {% if opportunities %}
            <table>
                <thead>
                    <tr>
                        <th>公司</th>
                        <th>轮次</th>
                        <th>金额</th>
                        <th>窗口剩余</th>
                        <th>信号强度</th>
                        <th>状态</th>
                    </tr>
                </thead>
                <tbody>
                    {% for opp in opportunities %}
                    <tr>
                        <td><strong>{{ opp.company_name }}</strong></td>
                        <td>{{ opp.round_type }}</td>
                        <td>{{ opp.amount_formatted }}</td>
                        <td>
                            {% if opp.window_days_remaining <= 7 %}
                            <span class="window urgent">{{ opp.window_days_remaining }}天 ⚠️</span>
                            {% elif opp.window_days_remaining <= 30 %}
                            <span class="window warning">{{ opp.window_days_remaining }}天</span>
                            {% else %}
                            <span class="window ok">{{ opp.window_days_remaining }}天</span>
                            {% endif %}
                        </td>
                        <td><span class="strength {{ opp.signal_strength|lower }}">{{ opp.signal_strength }}</span></td>
                        <td><span class="status {{ opp.status }}">{{ opp.status }}</span></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="empty" style="padding:40px;text-align:center;color:#64748b;">暂无商机</div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
