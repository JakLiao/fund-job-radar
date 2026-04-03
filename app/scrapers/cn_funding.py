"""Chinese funding news scraper (36kr RSS + other accessible sources).

Data sources:
1. 36kr RSS (https://36kr.com/feed) - works reliably
2. 投资界 (pedaily.cn) - accessible but requires JS rendering
3. 创业邦 (cyzone.cn) - accessible homepage

For job data, most major platforms (猎聘, 智联, 拉勾, BOSS直聘) are blocked by anti-bot.
We try 拉勾 API as fallback and use Greenhouse for Chinese companies that have it.
"""

import logging
import re
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import feedparser
import requests

# Prevent hanging
socket.setdefaulttimeout(10)

from ..models import FundingEvent

# Import industry classifier (project root is parent of app/)
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.cn_industry_classifier import classify_industry

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ==============================================================================
# Amount parsing - Chinese units (万/亿)
# ==============================================================================

def _parse_cn_amount(text: str) -> Optional[float]:
    """Parse Chinese funding amount from text.
    
    Handles:
    - X亿人民币 (100M CNY)
    - X千万人民币 (10M CNY)
    - X百万人民币 (1M CNY)
    - X万人民币 (10K CNY)
    - $XM / $X million
    - Plain numbers (filtered carefully)
    
    Returns amount in CNY (yuan).
    """
    if not text:
        return None
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # All amounts returned in CNY (yuan), no conversion needed
    # First try explicit digit patterns (with number group)
    digit_patterns = [
        # "X亿" + currency (e.g., "1亿人民币", "2亿美元")
        (r'(\d+(?:\.\d+)?)\s*亿\s*(?:美元|USD|刀|美)', 1e8 * 7.2),
        (r'(\d+(?:\.\d+)?)\s*亿\s*(?:人民币|元|RMB|CNY)?', 1e8),
        # "X千万" (~10M CNY)
        (r'(\d+(?:\.\d+)?)\s*千万\s*(?:人民币|元|RMB|美元|USD)?', 1e7),
        # "X百万" (~1M CNY)
        (r'(\d+(?:\.\d+)?)\s*百万\s*(?:人民币|元|RMB|美元|USD)?', 1e6),
        # "X万" + currency (with optional suffix)
        (r'(\d+(?:\.\d+)?)\s*万\s*(?:美元|USD)', 1e4 * 7.2),
        (r'(\d+(?:\.\d+)?)\s*万\s*(?:人民币|元|RMB)?', 1e4),
        # "$X million" style - convert USD to CNY
        (r'\$\s*(\d+(?:\.\d+)?)\s*百万', 1e6 * 7.2),
        (r'\$\s*(\d+(?:\.\d+)?)\s*M\b', 1e6 * 7.2),
        (r'\$\s*(\d+(?:\.\d+)?)\s*B\b', 1e9 * 7.2),
    ]
    
    for pattern, multiplier in digit_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount = float(match.group(1)) * multiplier
            if amount >= 10000:
                return amount
    
    # Then try "vague" patterns without explicit digit (数千万, 近千万, etc.)
    # Order matters: check more specific (数/近/超 + unit) before generic (千/百 alone)
    
    # More specific vague: 数千万, 近千万, etc. (ordered by specificity)
    specific_vague = [
        # (regex, amount in CNY)
        (r'近\s*亿', 8e7),
        (r'超\s*亿', 1e8),
        (r'上\s*亿', 1e8),
        (r'数\s*亿', 5e7),
        (r'近\s*千\s*万', 8e6),
        (r'逾\s*千\s*万', 9e6),
        (r'超\s*千\s*万', 1e7),
        (r'上\s*千\s*万', 1e7),
        (r'数\s*千\s*万', 5e6),
        (r'近\s*百\s*万', 8e5),
        (r'数\s*百\s*万', 5e5),
    ]
    
    # Check if more specific patterns cover a match first
    specific_match_found = False
    for pattern, amount in specific_vague:
        if re.search(pattern, text):
            # Check if a more specific pattern would also match at same position
            if amount >= 10000:
                return amount
    
    # Generic vague: 千万元 (meaning 数千万 range)
    if re.search(r'千\s*万', text):
        amount = 5e6
        if amount >= 10000:
            return amount
    
    return None


def _parse_round_type(text: str) -> Optional[str]:
    """Extract Chinese funding round type from text.
    
    Chinese rounds: 天使轮, Pre-A, A轮, A+轮, B轮, B+轮, C轮, D轮,
                    Pre-IPO, 战略投资, etc.
    """
    text_lower = text.lower()
    
    # Exclude words - these indicate non-funding events
    # Note: 'ipo' must be excluded only as standalone, not as part of 'pre-ipo'
    # So we use the original text_lower (not simplified) for exclude checking
    exclude_phrases = ['上市', '并购', '收购', '合并', '减持', '增发', '回购', '退市']
    # Also exclude standalone ipo/IPO (but not pre-ipo)
    # Match 'ipo' as full word with word boundaries
    ipo_match = re.search(r'\bipo\b', text_lower)
    pre_ipo_match = re.search(r'pre-?ipo', text_lower)
    if ipo_match and not pre_ipo_match:
        return None
    for phrase in exclude_phrases:
        if phrase in text_lower:
            return None
    
    # Round patterns - check in order of specificity
    round_map = [
        # Use negative lookbehind (?<![A-Za-z-]) to avoid A matching inside "Pre-A", etc.
        (r'D\+?\s*轮', 'D'),
        (r'C1\s*轮|C1轮', 'C'),
        (r'C\+?\s*轮', 'C'),
        (r'(?<![\w-])B\+?\s*轮', 'B'),
        (r'(?<![\w-])A\+?\s*轮', 'A'),
        (r'[Pp]re-?[Bb]\s*轮|Pre-B', 'Pre-B'),
        (r'[Pp]re-?[Aa]\s*轮|Pre-A', 'Pre-A'),
        (r'[Pp]re-?[Ii][\s-]*[Pp][\s-]*[Ii][\s-]*[Oo]|Pre-IPO', 'Pre-IPO'),
        (r'天使\+|天使\s*轮|天使投资', 'Angel'),
        (r'种子\s*轮|种子投资', 'Seed'),
        (r'战\s*略\s*投\s*资|战略融资', '战略投资'),
        (r'股\s*权\s*融\s*资', 'Equity'),
        (r'并\s*购|收\s*购', None),  # excluded
    ]
    
    for pattern, round_type in round_map:
        if round_type is None:
            continue  # skip exclusions
        if re.search(pattern, text, re.IGNORECASE):
            return round_type
    
    return None


def _extract_company_from_36kr_entry(title: str, desc: str) -> str:
    """Extract company name from 36kr article title and description.
    
    36kr titles follow patterns like:
    - "36氪首发 | 公司名 完成XXX轮融资"
    - "获X投资，公司名做了..."
    - "36氪独家 | 公司名 ..."
    - "公司名 被爆完成..."
    """
    # Clean HTML tags from description for analysis
    desc_clean = re.sub(r'<[^>]+>', ' ', desc)
    desc_clean = re.sub(r'\s+', ' ', desc_clean)
    
    # Try to extract from "公司名（下称"XX"）" pattern
    company_pattern = re.search(r'([\u4e00-\u9fa5]{2,15})(?:科技|智能|网络|信息|数据|机器人|系统|半导体|基因|生物|医疗|健康|能源|汽车|出行|物流|教育|金融|商业|服务|机器人)公司', desc_clean)
    if company_pattern:
        return company_pattern.group(1) + '公司'
    
    # Try to find "XXX公司（下称"XX"）" pattern
    company_aka = re.search(r'([\u4e00-\u9fa5]{2,10})公司（下称"([^"]+)"）', desc_clean)
    if company_aka:
        return company_aka.group(2) if len(company_aka.group(2)) >= 2 else company_aka.group(1) + '公司'
    
    # Try title patterns
    # "36氪首发 | 公司名 完成..."
    match = re.match(r'^36氪首发\s*\|\s*(.{2,20})\s', title)
    if match:
        return match.group(1).strip()
    
    # "获X投资，公司名..."
    match = re.match(r'^获[^，]+投资，(.{2,20?})\s*(?:做|成|是|获)', title)
    if match:
        return match.group(1).strip()
    
    # "公司名 获..." at start
    match = re.match(r'^([\u4e00-\u9fa5a-zA-Z0-9]{2,20})\s+(?:获|完成|拿到|宣布)', title)
    if match:
        name = match.group(1).strip()
        # Clean trailing punctuation
        name = re.sub(r'[，。、\s].*$', '', name)
        if len(name) >= 2:
            return name
    
    return ""


# ==============================================================================
# 36kr RSS Scraper
# ==============================================================================

def _extract_36kr_funding_events(entries: list) -> list:
    """Extract funding events from 36kr RSS entries.
    
    Entry is a funding event if:
    1. Title or description contains a clear funding round indicator (A/B/C/D轮, 天使轮, etc.)
    2. AND a company name can be identified
    3. OR title contains "获...投资" with funding amount
    """
    events = []
    
    for entry in entries:
        title = str(entry.get('title', ''))
        link = str(entry.get('link', ''))
        desc = str(entry.get('summary', entry.get('description', '')))
        
        if not title:
            continue
        
        # Strip HTML tags for text analysis
        desc_clean = re.sub(r'<[^>]+>', ' ', desc)
        desc_clean = re.sub(r'\s+', ' ', desc_clean)
        
        # Check if this looks like a funding announcement
        # Criteria: has funding round mention AND company name
        
        # Strategy 1: Explicit round in title or description
        round_title = _parse_round_type(title)
        round_desc = _parse_round_type(desc_clean)
        round_type = round_title or round_desc
        
        amount_title = _parse_cn_amount(title)
        amount_desc = _parse_cn_amount(desc_clean)
        amount = amount_title or amount_desc
        
        company = _extract_company_from_36kr_entry(title, desc_clean)
        
        # Strategy 2: "获...投资" pattern with amount (company mentioned as "XXX公司")
        has_investment_keyword = bool(re.search(r'获.+(?:投资|融资|资金)', title))
        
        if has_investment_keyword and not round_type:
            # Try to find explicit round in description
            round_desc = _parse_round_type(desc_clean)
            if round_desc:
                round_type = round_desc
            if not amount:
                amount = amount_desc
            
            # Try to find company in description
            if not company:
                company = _extract_company_from_36kr_entry(title, desc_clean)
        
        # Skip if no clear round type found
        if not round_type:
            logger.debug(f"Skipping (no round): {title[:60]}")
            continue
        
        # Skip if no company name found
        if not company or len(company) < 2:
            logger.debug(f"Skipping (no company): {title[:60]}")
            continue
        
        # Skip obvious non-funding articles
        # If amount is extremely large (like company valuation/IPO), skip
        if amount and amount > 10_000_000_000:  # > $10B is probably valuation not funding
            logger.debug(f"Skipping (amount too large ${amount:.0f}): {title[:60]}")
            continue
        
        # Parse date
        published_parsed = entry.get("published_parsed")
        if published_parsed:
            try:
                announcement_date = datetime(*published_parsed[:6])
            except Exception:
                announcement_date = datetime.now()
        else:
            announcement_date = datetime.now()
        
        event = FundingEvent(
            company_name=company,
            company_domain="",
            round_type=round_type,
            amount_cny=amount or 0.0,
            announcement_date=announcement_date,
            investors="",
            source_url=link,
            source="cn",
            industry_group=classify_industry(company) or "",
        )
        events.append(event)
        logger.info(f"36kr funding: {company} | {round_type} | ${(amount or 0):,.0f}")
    
    return events


def fetch_36kr_fundings(limit: int = 50) -> list[FundingEvent]:
    """
    Fetch funding events from 36kr RSS feed.
    
    Returns a list of FundingEvent objects with parsed data.
    """
    events = []
    
    try:
        feed = feedparser.parse("https://36kr.com/feed")
        if feed.bozo and feed.bozo_exception:
            logger.warning(f"36kr RSS parsing issue: {feed.bozo_exception}")
    except Exception as e:
        logger.error(f"Failed to fetch 36kr RSS: {e}")
        return events
    
    entries = feed.entries[:limit]
    events = _extract_36kr_funding_events(entries)
    
    logger.info(f"Total funding events parsed from 36kr: {len(events)}")
    return events


# ==============================================================================
# 投资界 (pedaily.cn) Scraper
# ==============================================================================

def _fetch_pedaily_fundings() -> list[FundingEvent]:
    """
    Fetch funding events from 投资界 (pedaily.cn).
    
    Uses the /first/t76/ page which contains funding news flash items
    as data-title attributes on image elements.
    
    Source: https://www.pedaily.cn/first/t76/
    """
    events = []
    
    try:
        r = requests.get(
            "https://www.pedaily.cn/first/t76/",
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        r.encoding = r.apparent_encoding or 'utf-8'
        text = r.text
        
        if r.status_code != 200:
            logger.debug(f"pedaily /first/t76/ returned {r.status_code}")
            return events
        
        # Extract funding news from data-title attributes
        # e.g. '深耕多模态AIOS，无界方舟连续完成数亿元Pre-A轮融资'
        data_titles = re.findall(r'data-title="([^"]+)"', text)
        
        for title in data_titles:
            if not title or len(title) < 5:
                continue
            
            # Skip if clearly not a funding announcement
            funding_kws = ['融资', '投资', '轮', '获', '万元', '亿', '天使']
            if not any(kw in title for kw in funding_kws):
                continue
            
            # Extract company name
            company = _extract_company_from_pedaily_title(title)
            
            # Extract round type
            round_type = _parse_round_type(title)
            
            # Extract amount
            amount = _parse_cn_amount(title)
            
            if not round_type and not amount:
                continue
            
            if not company:
                # Try to find company name from the first part of title
                # Pattern: "XXX完成YYY融资" or "XXX获YYY融资"
                company_match = re.match(r'^([^，,、。完成获拿到]+)', title)
                if company_match:
                    company = company_match.group(1).strip()
                    # Remove trailing particles
                    company = re.sub(r'[公司]$', '', company)
            
            if not company or len(company) < 2:
                continue
            
            event = FundingEvent(
                company_name=company,
                company_domain="",
                round_type=round_type or "Unknown",
                amount_cny=amount or 0.0,
                announcement_date=datetime.now(),
                investors="",
                source_url="https://www.pedaily.cn/first/t76/",
                source="cn",
                industry_group=classify_industry(company) or "",
            )
            events.append(event)
            logger.info(f"pedaily funding: {company} | {round_type} | ${(amount or 0):,.0f}")
            
    except Exception as e:
        logger.debug(f"pedaily /first/t76/ fetch failed: {e}")
    
    return events


def _extract_company_from_pedaily_title(title: str) -> str:
    """Extract company name from pedaily funding news title.
    
    Patterns:
    - "深耕多模态AIOS，无界方舟连续完成数亿元Pre-A轮融资" -> "无界方舟"
    - "鹰瞰智翼获千万元天使轮融资" -> "鹰瞰智翼"
    - "清华系具身企业「光象科技」半年融资超1亿" -> "光象科技"
    - "法奥机器人完成近1亿美元C轮融资" -> "法奥机器人"
    - "艾利特机器人完成6亿元D+轮融资，布局AI产业链" -> "艾利特机器人"
    """
    # Pattern 1: Parenthetical company name first 「XXX」 or 《XXX》
    paren_match = re.search(r'[「《]([^」》\s]{2,20})[」》]', title)
    if paren_match:
        company = paren_match.group(1).strip()
        if len(company) >= 2:
            return company
    
    # Pattern 2: After comma, before 完成/获 - look for company name + (optional adverb) + 完成/获
    # e.g. "深耕多模态AIOS，无界方舟连续完成..." -> "无界方舟"
    # e.g. "布局AI产业链，艾利特机器人完成..." -> "艾利特机器人"
    comma_match = re.search(r'，([^，。\s]{2,25}?)\s*(?:完成|获|拿到)', title)
    if comma_match:
        segment = comma_match.group(1).strip()
        # The company name is the part before action verbs/adverbs
        # Clean up trailing action words
        segment = re.sub(r'(连续|又|再|已|将|正在|刚刚|近期)+$', '', segment)
        segment = segment.strip()
        if len(segment) >= 2:
            # Additional filter: skip obvious non-company prefixes
            bad_prefixes = ['深耕', '布局', '专注', '聚焦', '致力', '打造', '推出', 
                           '获得', '首创', '再', '已', '将', '新', '清华系', 
                           '北大系', '阿里系', '腾讯系', '国内', '国外', '率先']
            if not any(segment.startswith(p) for p in bad_prefixes):
                return segment
    
    # Pattern 3: "公司名 完成/获/拿到 ... 融资" at the start of title
    # e.g. "富德金煜完成1.2亿元Pre-A轮融资" -> "富德金煜"
    match = re.match(r'^([^，。、\s]{2,25}?)\s*(?:完成|获|拿到)', title)
    if match:
        company = match.group(1).strip()
        # Remove trailing action words
        company = re.sub(r'(连续|又|再|已|将|正在|刚刚)+$', '', company)
        company = company.strip()
        if len(company) >= 2:
            return company
    
    # Pattern 4: Try to extract company name before "融资" at end
    # e.g. "某公司... 融资" - take the part just before 融资
    match = re.search(r'([^，。、\s]{2,20})\s*完成.{0,5}?融资', title)
    if match:
        company = match.group(1).strip()
        company = re.sub(r'(连续|又|再|已|将)+$', '', company)
        if len(company) >= 2:
            return company
    
    return ""


# ==============================================================================
# 创业邦 (cyzone.cn) Scraper  
# ==============================================================================

def _fetch_cyzone_fundings() -> list[FundingEvent]:
    """
    Fetch funding events from 创业邦 (cyzone.cn).
    
    The homepage has JS-rendered content but some sections may be accessible.
    We try to extract funding news from the homepage HTML.
    """
    events = []
    
    try:
        r = requests.get("https://www.cyzone.cn/", timeout=10, headers=HEADERS)
        r.encoding = r.apparent_encoding or 'utf-8'
        text = r.text
        
        # Look for article links with funding keywords
        article_pattern = r'<a[^>]+href="(https://www\.cyzone\.cn/article/\d+[^"]*)"[^>]*>([^<]*?(?:融资|投资|轮)[^<]*)</a>'
        matches = re.findall(article_pattern, text, re.IGNORECASE)
        
        for url, title in matches[:20]:
            title = title.strip()
            if not title or len(title) < 5:
                continue
            
            round_type = _parse_round_type(title)
            amount = _parse_cn_amount(title)
            company = _extract_company_from_36kr_entry(title, "")
            
            if round_type is None:
                continue
            if not company:
                continue
            
            event = FundingEvent(
                company_name=company,
                company_domain="",
                round_type=round_type,
                amount_cny=amount or 0.0,
                announcement_date=datetime.now(),
                investors="",
                source_url=url,
                source="cn",
                industry_group=classify_industry(company) or "",
            )
            events.append(event)
            logger.info(f"cyzone funding: {company} {round_type}")
            
    except Exception as e:
        logger.debug(f"cyzone fetch failed: {e}")
    
    return events


# ==============================================================================
# Main entry point
# ==============================================================================

def fetch_cn_fundings(limit: int = 50) -> list[FundingEvent]:
    """
    Fetch funding events from all accessible Chinese sources.
    
    Priority:
    1. 36kr RSS (most reliable)
    2. 投资界 RSS fallback
    3. 创业邦 homepage HTML fallback
    
    Args:
        limit: Maximum number of events per source
    
    Returns:
        List of FundingEvent objects with source='cn'
    """
    all_events = []
    seen_companies = set()
    
    # Source 1: 36kr RSS (most reliable)
    logger.info("Fetching fundings from 36kr RSS...")
    try:
        events = fetch_36kr_fundings(limit=limit)
        for event in events:
            key = (event.company_name, event.round_type, int(event.amount_cny / 10000))
            if key not in seen_companies:
                all_events.append(event)
                seen_companies.add(key)
    except Exception as e:
        logger.error(f"36kr fetch failed: {e}")
    
    # Source 2: 投资界 RSS
    logger.info("Fetching fundings from 投资界...")
    try:
        events = _fetch_pedaily_fundings()
        for event in events:
            key = (event.company_name, event.round_type, int(event.amount_cny / 10000))
            if key not in seen_companies:
                all_events.append(event)
                seen_companies.add(key)
    except Exception as e:
        logger.error(f"投资界 fetch failed: {e}")
    
    # Source 3: 创业邦 HTML
    logger.info("Fetching fundings from 创业邦...")
    try:
        events = _fetch_cyzone_fundings()
        for event in events:
            key = (event.company_name, event.round_type, int(event.amount_cny / 10000))
            if key not in seen_companies:
                all_events.append(event)
                seen_companies.add(key)
    except Exception as e:
        logger.error(f"创业邦 fetch failed: {e}")
    
    logger.info(f"Total CN funding events: {len(all_events)}")
    return all_events
