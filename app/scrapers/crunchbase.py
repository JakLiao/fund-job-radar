"""Crunchbase API scraper — Phase 2.

Crunchbase 提供全球融资数据，覆盖范围广，数据质量高。

⚠️ 注意：Crunchbase API 需要注册并获取 API Key
- 免费版：每天 100 次请求
- 付费版：无限制

注册地址：https://www.crunchbase.com/
API Key 获取：https://www.crunchbase.com/backend/labs/labs_api_keys

配置方法：
1. 在 https://www.crunchbase.com 注册账号
2. 访问 https://www.crunchbase.com/backend/labs/labs_api_keys 创建 API Key
3. 将 Key 填入 config.yaml 的 apis.crunchbase_key

API 文档：https://data.crunchbase.com/docs
"""

import logging
from typing import Optional

import requests

from ..models import FundingEvent

logger = logging.getLogger(__name__)

# Crunchbase API endpoints
CB_API_BASE = "https://api.crunchbase.com/api/v4/odata/v4"
CB_HEADERS = {
    "accept": "application/json",
}

REQUEST_TIMEOUT = 15


def _convert_crunchbase_to_funding_event(cb_data: dict) -> Optional[FundingEvent]:
    """Convert Crunchbase API response to FundingEvent model."""
    try:
        # Extract nested data
        org = cb_data.get("org", {})
        funding_round = cb_data.get("funding_round", {})
        
        company_name = org.get("name", "")
        if not company_name:
            return None
        
        # Get funding details
        round_type = funding_round.get("round_type", {}).get("value", "Unknown")
        amount_cny = funding_round.get("money_raised", {}).get("value_usd", 0) or \
                     funding_round.get("money_raised", {}).get("value", 0) or 0
        
        # Get date
        announced_on = cb_data.get("announced_on", "")
        
        # Get source URL
        cb_url = cb_data.get("url", "")
        
        return FundingEvent(
            company_name=company_name,
            company_domain=org.get("domain", ""),
            round_type=round_type,
            amount_cny=float(amount_cny) * 7.2,  # Convert USD → CNY
            announcement_date=_parse_date(announced_on),
            investors=_extract_investors(cb_data),
            source_url=cb_url or f"https://www.crunchbase.com/organization/{org.get('identifier', {}).get('value', '')}",
            source="crunchbase",
        )
    except Exception as e:
        logger.error(f"Failed to convert Crunchbase data: {e}")
        return None


def _parse_date(date_str: str):
    """Parse date string to datetime (delegated to shared utils)."""
    from ..utils.date_parser import parse_date
    return parse_date(date_str)


def _extract_investors(cb_data: dict) -> str:
    """Extract investor names from Crunchbase data."""
    investors = []
    lead_investors = cb_data.get("lead_investors", [])
    if lead_investors:
        for inv in lead_investors:
            if isinstance(inv, dict):
                investors.append(inv.get("name", ""))
            elif isinstance(inv, str):
                investors.append(inv)
    return ", ".join(filter(None, investors))


def fetch_crunchbase_fundings(
    api_key: str,
    days: int = 30,
    limit: int = 100,
    min_amount: float = 100000,
) -> list[FundingEvent]:
    """
    Fetch recent funding rounds from Crunchbase API.
    
    Args:
        api_key: Crunchbase API key
        days: Number of days to look back
        limit: Maximum number of results
        min_amount: Minimum funding amount in USD
    
    Returns:
        List of FundingEvent objects
    """
    if not api_key:
        logger.warning("Crunchbase API key not configured")
        return []
    
    events = []
    
    try:
        headers = {**CB_HEADERS, "X-cb-user-key": api_key}
        
        # Crunchbase v4 OData API
        # Filter for recent funding rounds
        url = (
            f"{CB_API_BASE}/funding_rounds?"
            f"$filter=announced_on gt datetimeoffset'{_days_ago(days)}' "
            f"and money_raised/value_usd ge {min_amount}&"
            f"$orderby=announced_on desc&"
            f"$top={limit}&"
            f"$select=identifier,announced_on,money_raised,round_type,"
            f"org,lead_investors,cb_url"
        )
        
        logger.info(f"Querying Crunchbase API...")
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 401:
            logger.error("Crunchbase API authentication failed. Check your API key.")
            return []
        elif response.status_code != 200:
            logger.error(f"Crunchbase API error: {response.status_code}")
            return []
        
        data = response.json()
        items = data.get("value", [])
        
        for item in items:
            event = _convert_crunchbase_to_funding_event(item)
            if event:
                events.append(event)
                logger.debug(f"Parsed Crunchbase: {event.company_name}")
        
        logger.info(f"Fetched {len(events)} Crunchbase funding events")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Crunchbase request failed: {e}")
    except Exception as e:
        logger.error(f"Crunchbase parsing failed: {e}")
    
    return events


def get_organization_funding(identifier: str, api_key: str) -> dict:
    """
    Get funding rounds for a specific organization.
    
    Args:
        identifier: Company identifier (name, permalink, or UUID)
        api_key: Crunchbase API key
    
    Returns:
        Dictionary with organization funding info
    """
    if not api_key:
        return {}
    
    try:
        headers = {**CB_HEADERS, "X-cb-user-key": api_key}
        
        # Search for organization
        url = f"{CB_API_BASE}/organizations?$filter=identifier/value eq '{identifier}'&$select=*"
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            items = data.get("value", [])
            if items:
                return items[0]
                
    except Exception as e:
        logger.error(f"Failed to fetch organization: {e}")
    
    return {}


def _days_ago(days: int) -> str:
    """Get date string for N days ago."""
    from datetime import datetime, timedelta
    date = datetime.now() - timedelta(days=days)
    return date.strftime("%Y-%m-%dT00:00:00")
