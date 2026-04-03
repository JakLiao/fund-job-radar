"""TechCrunch RSS feed scraper for funding events."""

import logging
import re
import socket
from datetime import datetime
from typing import Optional

import feedparser

# Prevent feedparser from hanging indefinitely
socket.setdefaulttimeout(10)

from ..models import FundingEvent

logger = logging.getLogger(__name__)

TC_RSS_URL = "https://techcrunch.com/feed/"

# Regex patterns for extracting funding info from TC titles/descriptions
# Examples: "Startup raises $10M Series A", "Company lands $50M Series B"
# Using case-insensitive matching
SEED_PATTERNS = [
    r"\bseed\b",
    r"\bpre-?seed\b",
    r"\bangel\b",
]
SERIES_PATTERNS = [
    r"\bSeries\s+([A-Z])\b",
]
EXCLUDE_PATTERNS = [
    r"\bipo\b",
    r"\bmerger\b",
    r"\bacqui(?:sition|hired)\b",
    r"\bgoes public\b",
    r"\bgo public\b",
]

# Funding amount patterns — handles $10M / 10M / $10 million / 10 million / $1.5B / 1.5B / 1.5 billion
AMOUNT_PATTERNS = [
    r"\$?\s*(\d+(?:\.\d+)?)\s*([kmb])\b",  # $10M, 10M, $10K, 10K, $1B, 1B
    r"\$?\s*(\d+(?:\.\d+)?)\s*(million|billion|thousand)\b",  # $8.4 million, 8.4 million, $1.5 billion
    r"\$?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?)\b",  # $10,000,000
]


def _parse_amount(amount_str: str) -> Optional[float]:
    """Parse a funding amount string and return USD value."""
    if not amount_str:
        return None
    amount_str = amount_str.lower().strip()
    # Normalize
    amount_str = amount_str.replace(",", "").replace("$", "").strip()

    multiplier = 1.0
    if amount_str.endswith("k"):
        multiplier = 1_000.0
        amount_str = amount_str[:-1]
    elif amount_str.endswith("m"):
        multiplier = 1_000_000.0
        amount_str = amount_str[:-1]
    elif amount_str.endswith("b"):
        multiplier = 1_000_000_000.0
        amount_str = amount_str[:-1]
    elif amount_str.endswith("million") or amount_str.endswith("thousand") or amount_str.endswith("billion"):
        if amount_str.endswith("billion"):
            multiplier = 1_000_000_000.0
            amount_str = amount_str[:-7]
        elif amount_str.endswith("million"):
            multiplier = 1_000_000.0
            amount_str = amount_str[:-7]
        elif amount_str.endswith("thousand"):
            multiplier = 1_000.0
            amount_str = amount_str[:-8]

    try:
        value = float(amount_str)
        return value * multiplier
    except ValueError:
        return None


def _extract_round(text: str) -> Optional[str]:
    """Extract funding round type from text (case-insensitive)."""
    text_lower = text.lower()
    
    # Check for excluded patterns first
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, text_lower):
            return None
    
    # Check for Series
    for pattern in SERIES_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    
    # Check for Seed patterns
    for pattern in SEED_PATTERNS:
        if re.search(pattern, text_lower):
            return "Seed"
    
    return None


def _extract_amount(text: str) -> Optional[float]:
    """Extract funding amount from text (case-insensitive)."""
    text_lower = text.lower()
    
    for pattern in AMOUNT_PATTERNS:
        matches = re.findall(pattern, text_lower)
        for match in matches:
            if isinstance(match, tuple):
                num_str, suffix = match[0], match[1]
            else:
                num_str = match
                suffix = ""
            
            # Try with suffix (handles both single-char: m/k/b and full words: million/billion/thousand)
            if suffix:
                amount_str = num_str + suffix
                amount = _parse_amount(amount_str)
                if amount and amount >= 10_000:  # Minimum $10k filter
                    return amount
            
            # Try without suffix (for comma-separated numbers)
            if "," in num_str:
                amount = _parse_amount(num_str)
                if amount and amount >= 10_000:
                    return amount
    
    return None


def _extract_company_name(title: str) -> str:
    """Extract company name from article title.
    
    Returns empty string if no valid company name can be extracted.
    """
    # TC titles often look like: "Company Name raises $XXM Series A"
    # or "Company Name lands $XXM for Series A"
    # or "Company Name closes $XXM Series A"
    
    title_lower = title.lower()
    
    # Skip obvious non-funding-raise titles (article headlines, not funding announcements)
    # These patterns indicate general news/analysis, not specific funding events
    skip_patterns = [
        r"^it's not your imagination",
        r"^how to ",
        r"^what is ",
        r"^why ",
        r"^when ",
        r"^this week in",
        r"^what's ",
        r"^here's ",
        r"^the future of",
        r"^everything you",
        r"^a guide to",
        r"^can ",
        r"^should ",
        r"^will ",
        r"^is ",
        r"^are ",
        r"^was ",
        r"^were ",
    ]
    
    for pattern in skip_patterns:
        if re.match(pattern, title_lower):
            # Even with these prefixes, try to find company after colon
            # e.g., "It's not your imagination: AI startup X raises..."
            if ":" in title:
                remaining = title.split(":")[-1].strip()
                # Look for funding pattern after colon
                match = re.match(r"(.+?)\s+(?:raises|lands|secures|closes|gets|wins)\s+", remaining, re.IGNORECASE)
                if match:
                    company = match.group(1).strip()
                    if len(company) >= 2:
                        return company.title()
            # No valid company found after colon, return empty
            return ""
    
    # Standard extraction: find company before funding keywords
    # Pattern: "Company Name raises/lands/secures $XXM [Series/Seed]"
    patterns = [
        r"^(.+?)\s+(?:raises|lands|secures|closes|gets|wins)\s+\$",  # Company raises $10M
        r"^(.+?)\s+(?:raises|lands|secures|closes|gets|wins)\s+\d",  # Company raises 10M
        r"^(.+?)\s+(?:in\s+)?\$[\d.,]+[kmb]?\s+(?:series|seed)",  # Company in $10M Series A
        r"^(.+?)\s+(?:to\s+)?acquire",  # Company to acquire
    ]
    
    for pattern in patterns:
        match = re.match(pattern, title, re.IGNORECASE)
        if match:
            company = match.group(1).strip()
            # Clean up
            company = re.sub(r"\s*[-–—]\s*.+$", "", company)  # Remove after hyphen
            company = re.sub(r"\s+in\s+.+$", "", company, flags=re.IGNORECASE)  # Remove "in..."
            if company and len(company) >= 2:
                return company
    
    # Fallback: just clean up the title
    title = re.sub(r"\s+(raises|lands|secures|closes|gets|wins)\s+.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+in\s+\$[\d.,]+[kmb]?\s+\w+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*[-–—]\s*.+$", "", title)
    title = re.sub(r"\s+to\s+.+$", "", title, flags=re.IGNORECASE)
    result = title.strip()
    
    # Final validation: if result is too long (>50 chars) or looks like a sentence, skip it
    if len(result) > 50 or result.endswith("."):
        return ""
    
    return result


def fetch_techcrunch_fundings(limit: int = 50) -> list[FundingEvent]:
    """
    Fetch funding events from TechCrunch RSS feed.
    
    Returns a list of FundingEvent objects with parsed data.
    Filters out entries without clear funding amounts.
    """
    events = []
    
    try:
        feed = feedparser.parse(TC_RSS_URL)
        if feed.bozo and feed.bozo_exception:
            logger.warning(f"RSS feed parsing issue: {feed.bozo_exception}")
    except Exception as e:
        logger.error(f"Failed to fetch TechCrunch RSS: {e}")
        return events

    for entry in feed.entries[:limit]:
        try:
            # Get title safely
            title = str(entry.get("title", ""))
            link = str(entry.get("link", ""))
            
            if not title:
                continue
            
            # Extract from title first
            round_type = _extract_round(title)
            amount = _extract_amount(title)
            
            # Try description if title didn't yield results
            if amount is None or round_type is None:
                summary = str(entry.get("summary", entry.get("description", "")))[:2000]
                if amount is None:
                    amount = _extract_amount(summary)
                if round_type is None:
                    round_type = _extract_round(summary)
            
            # Skip if no amount or round type found (filter non-funding news)
            if amount is None:
                logger.debug(f"Skipping (no amount): {title}")
                continue
            if round_type is None:
                logger.debug(f"Skipping (no round): {title}")
                continue

            company_name = _extract_company_name(title)
            # Skip entries where we couldn't extract a valid company name
            if not company_name or len(company_name) < 2:
                logger.debug(f"Skipping (no company name): {title[:50]}")
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
                company_name=company_name,
                company_domain="",
                round_type=round_type,
                amount_cny=amount * 7.2,  # Convert USD → CNY
                announcement_date=announcement_date,
                investors="",
                source_url=link,
                source="tc",
            )
            events.append(event)
            logger.info(f"Parsed funding: {company_name} {round_type} USD {amount:,.0f} = CNY ¥{amount*7.2:,.0f}")
        except Exception as e:
            logger.error(f"Failed to parse entry '{title[:50]}': {e}")
            continue

    logger.info(f"Total funding events parsed from TC: {len(events)}")
    return events
