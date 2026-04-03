"""飞书群机器人推送 notification for Fund Job Radar."""

import logging
from datetime import datetime, time
from typing import Optional

import requests

from .config import get_config
from .database import get_pending_opportunities, get_funding_by_id, update_opportunity_status

logger = logging.getLogger(__name__)

# HTTP timeout in seconds
REQUEST_TIMEOUT = 10


def _format_amount(amount_cny: float, source: str = "") -> str:
    """Format CNY amount for Feishu notification display."""
    if amount_cny >= 100_000_000:
        return f"¥{amount_cny/100_000_000:.1f}亿元"
    elif amount_cny >= 10_000_000:
        return f"¥{amount_cny/10_000_000:.1f}千万元"
    elif amount_cny >= 1_000_000:
        return f"¥{amount_cny/1_000_000:.1f}百万元"
    elif amount_cny >= 10_000:
        return f"¥{amount_cny/10_000:.1f}万元"
    elif amount_cny == 0:
        return "金额未披露" if source == "edgar" else "未知"
    else:
        return f"¥{amount_cny:,.0f}元"


def _is_quiet_hours() -> bool:
    """Check if current time is within quiet hours."""
    config = get_config()
    now = datetime.now()
    current_time = now.time()
    
    quiet_start = time.fromisoformat(config.quiet_hours_start)
    quiet_end = time.fromisoformat(config.quiet_hours_end)
    
    if quiet_start <= quiet_end:
        return quiet_start <= current_time <= quiet_end
    else:
        return current_time >= quiet_start or current_time <= quiet_end


def _send_feishu_notification(title: str, content: str) -> bool:
    """
    Send a notification via 飞书群机器人 Webhook.
    
    Args:
        title: Notification title
        content: Notification body content
    
    Returns:
        True if sent successfully, False otherwise
    """
    config = get_config()
    webhook = config.feishu_webhook
    
    if not webhook or webhook == "YOUR_WEBHOOK":
        logger.warning("飞书 Webhook not configured, skipping notification")
        return False
    
    # Format: title + separator + content
    full_text = f"{title}\n{content}"
    
    payload = {
        "msg_type": "text",
        "content": {
            "text": full_text
        }
    }
    
    try:
        response = requests.post(webhook, json=payload, timeout=REQUEST_TIMEOUT)
        result = response.json()
        
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            logger.info(f"飞书 notification sent: {title}")
            return True
        else:
            logger.error(f"飞书 error: {result}")
            return False
    except requests.exceptions.Timeout:
        logger.error("飞书 request timed out")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"飞书 request failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending notification: {e}")
        return False


def push_funding_alert(company_name: str, round_type: str, amount_cny: float,
                      window_days: int, recommended_action: str, source: str = "TechCrunch",
                      industry_group: str = "") -> bool:
    """
    Push a single funding alert notification.
    
    Args:
        company_name: Name of the funded company
        round_type: Funding round type
        amount_cny: Amount raised in CNY
        window_days: Remaining opportunity window days
        recommended_action: Recommended action text
        source: Data source name
        industry_group: Industry classification (optional)
    
    Returns:
        True if sent successfully
    """
    if _is_quiet_hours():
        logger.info("Quiet hours active, skipping notification")
        return False
    
    # Get hiring info for this company
    hiring_info = None
    try:
        from .scrapers.jobs import fetch_job_postings, get_company_hiring_info
        # Try Greenhouse first (most reliable)
        gh_postings = fetch_job_postings(company_name)
        if gh_postings:
            total_gh = sum(p.job_count or 1 for p in gh_postings)
            hiring_info = {
                "is_hiring": True,
                "total_positions": total_gh,
                "sources": ["greenhouse"],
            }
        else:
            # Fallback to LinkedIn/Indeed
            hiring_info = get_company_hiring_info(company_name)
    except Exception as e:
        logger.debug(f"Failed to get hiring info: {e}")
    
    # Format amount
    amount_str = _format_amount(amount_cny, source)

    # Source icon
    if source == "cn":
        source_icon = "🟠"
        source_name = "36kr/投资界"
    elif source == "tc":
        source_icon = "🔵"
        source_name = "TechCrunch"
    else:
        source_icon = "🟢"
        source_name = "EDGAR"
    
    title = f"{source_icon} 融资信号捕获 | {company_name}"
    
    # Build content
    content_lines = [
        f"公司：{company_name}",
        f"轮次：{round_type} | 金额：{amount_str}",
        f"窗口剩余：约{window_days}天",
        f"推荐动作：{recommended_action}",
        f"来源：{source_name}",
    ]
    
    # Add industry info if available
    if industry_group:
        content_lines.append(f"行业：{industry_group}")
    
    # Add hiring info if available
    if hiring_info and hiring_info.get("is_hiring"):
        total_positions = hiring_info.get("total_positions", 0)
        if total_positions > 0:
            content_lines.append("")
            content_lines.append(f"💼 招聘信号：{total_positions} 个职位（Greenhouse）")
        else:
            content_lines.append("")
            content_lines.append("💼 招聘信息：")
            if hiring_info.get("linkedin_url"):
                content_lines.append(f"LinkedIn：{hiring_info['linkedin_url']}")
            if hiring_info.get("indeed_url"):
                content_lines.append(f"Indeed：{hiring_info['indeed_url']}")
    
    content = "\n".join(content_lines)
    
    return _send_feishu_notification(title, content)


def push_daily_summary() -> bool:
    """
    Push a daily summary of all pending opportunities.
    
    Returns:
        True if sent successfully
    """
    opportunities = get_pending_opportunities()
    
    if not opportunities:
        logger.info("No pending opportunities for daily summary")
        return True
    
    # Build summary content
    content_lines = [
        f"📊 融资-招聘信号日报 ({datetime.now().strftime('%Y-%m-%d')})\n",
        f"共发现 {len(opportunities)} 个新机会：\n",
    ]
    
    # Count by source
    tc_count = 0
    edgar_count = 0
    edgar_no_amount = 0
    
    for opp in opportunities:
        funding = get_funding_by_id(opp.funding_event_id)
        if funding:
            if funding.source == "edgar":
                edgar_count += 1
                if funding.amount_cny == 0:
                    edgar_no_amount += 1
            else:
                tc_count += 1
    
    # Update summary header
    summary_parts = []
    if tc_count > 0:
        summary_parts.append(f"{tc_count}条 TechCrunch")
    if edgar_count > 0:
        summary_parts.append(f"{edgar_count}条 EDGAR")
    source_info = " | ".join(summary_parts) if summary_parts else "暂无"
    
    content_lines = [
        f"📊 融资-招聘信号日报 ({datetime.now().strftime('%Y-%m-%d')})\n",
        f"共发现 {len(opportunities)} 个新机会：{source_info}\n",
    ]
    
    if edgar_no_amount > 0:
        content_lines.append(f"(EDGAR数据不含金额，仅供参考)\n")
    
    for opp in opportunities[:10]:
        funding = get_funding_by_id(opp.funding_event_id)
        if funding:
            if funding.source == "cn":
                source_icon = "🟠"
            elif funding.source == "tc":
                source_icon = "🔵"
            else:
                source_icon = "🟢"
            
            # Handle amount display
            amount_str = _format_amount(funding.amount_cny, funding.source)
            
            # Industry info
            industry_info = f" | 行业：{funding.industry_group}" if funding.industry_group else ""
            
            content_lines.append(
                f"{source_icon} {opp.company_name}{industry_info}\n"
                f"   轮次：{funding.round_type} | 金额：{amount_str}\n"
                f"   窗口剩余：约{opp.window_days_remaining}天\n"
                f"   推荐：{opp.recommended_action}\n"
                f"   信号强度：{opp.signal_strength}\n"
            )
        update_opportunity_status(opp.id, "sent")
    
    if len(opportunities) > 10:
        content_lines.append(f"\n... 还有 {len(opportunities) - 10} 个机会")
    
    title = f"📊 融资日报 | {len(opportunities)} 个新机会"
    content = "\n".join(content_lines)
    
    return _send_feishu_notification(title, content)


def push_pending_notifications() -> int:
    """
    Push all pending opportunity notifications.
    
    Returns:
        Number of notifications sent
    """
    opportunities = get_pending_opportunities()
    sent_count = 0
    
    for opp in opportunities:
        funding = get_funding_by_id(opp.funding_event_id)
        if not funding:
            continue
        
        # Allow EDGAR events with $0 amount but mark as undisclosed
        # (already filtered in push_funding_alert amount display)
        
        success = push_funding_alert(
            company_name=opp.company_name,
            round_type=funding.round_type,
            amount_cny=funding.amount_cny,
            window_days=opp.window_days_remaining,
            recommended_action=opp.recommended_action,
            source=f"tc" if funding.source == "tc" else funding.source,
            industry_group=getattr(funding, 'industry_group', '') or '',
        )
        
        if success:
            update_opportunity_status(opp.id, "sent")
            sent_count += 1
    
    return sent_count
