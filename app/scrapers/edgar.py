"""SEC EDGAR Form D scraper - Phase 2.

Form D 是美国证券交易委员会(SEC)要求的融资披露文件。
25万美元以上的私募融资必须提交 Form D。
数据来源：https://www.sec.gov/cgi-bin/browse-edgar

优点：
- 法律强制披露，数据权威
- 完全免费
- 包含真实融资金额（不是估值）
- 覆盖美国成长期公司

Form D 关键字段：
- CompanyName: 公司名称
- Amount: 融资金额（USD）
- DateOfSale: 融资日期
- StateOfInc: 注册州
- Industry: 行业分类
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

from ..models import FundingEvent

logger = logging.getLogger(__name__)

# SEC EDGAR API endpoints
EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_API_URL = "https://efts.sec.gov/LATEST/search-index"
REQUEST_TIMEOUT = 15
USER_AGENT = "Fund Job Radar (fund-job-radar@example.com)"

# Form D states (US states + DC + territories)
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"
}

# Investment fund indicators - these are likely NOT startup companies
# Must appear as a significant word in the name, not just as a company type suffix
FUND_KEYWORDS = [
    "fund", "capital", "ventures", "partners", "asset management",
    "investment", "advisors", "advisory", "equity", "hedge",
    "private equity", "credit opportunities", "offshore",
    "growth fund", "opportunity fund", "real estate",
    "endowment", "pension", "trust", "endowment",
]

# Common legitimate startup suffixes - these are OK
OK_SUFFIXES = [
    "inc", "inc.", "incorporated",
    "corp", "corp.", "corporation",
    "llc", "l.l.c.", "ltd", "ltd.",
]

# Minimum amount threshold for filtering
MIN_STARTUP_AMOUNT = 500000  # $500k - smaller deals are often funds


def _get_default_date_range() -> tuple[str, str]:
    """Get default date range for EDGAR search (last 30 days)."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def _parse_edgar_date(date_str: str) -> datetime:
    """Parse EDGAR date format to datetime (delegated to shared utils)."""
    from ..utils.date_parser import parse_date
    return parse_date(date_str)


def _is_likely_fund(company_name: str) -> bool:
    """
    Check if a company name looks like an investment fund, not a startup.

    Investment funds typically have keywords like:
    - Fund, Capital, Ventures, Partners, Holdings, etc.

    Normal company suffixes like Inc, Corp, LLC are OK.
    """
    name_lower = company_name.lower()

    # Check for fund-specific keywords
    for keyword in FUND_KEYWORDS:
        if keyword in name_lower:
            return True

    # Check if name is ONLY a suffix (e.g., "LLC" alone)
    stripped = name_lower.strip()
    for suffix in OK_SUFFIXES:
        if stripped == suffix:
            return True

    # If name ends with "L.P.", "LP", "Ltd" (limited partnership / limited company)
    # these are often funds
    if name_lower.endswith(" l.p.") or name_lower.endswith(" lp"):
        return True
    if name_lower.endswith(", l.p.") or name_lower.endswith(", lp"):
        return True

    return False


def _estimate_startup_round(amount: float) -> str:
    """
    Estimate funding round based on amount.

    Form D doesn't have round type, so we estimate from amount.
    """
    if amount >= 50_000_000:
        return "C+"
    elif amount >= 15_000_000:
        return "B"
    elif amount >= 5_000_000:
        return "A"
    elif amount >= 250_000:
        return "Seed"
    else:
        return "Seed"


def _extract_amount_from_xml(xml_content: str) -> Optional[float]:
    """Extract total amount from Form D XML."""
    try:
        root = ET.fromstring(xml_content)
        # Try different namespace patterns
        namespaces = [
            "",
            "http://www.sec.gov/edgar/document/northbound",
        ]
        for ns in namespaces:
            # Try various element paths
            for path in [
                f".//{ns}Amount",
                f".//{ns}TotalOfferingAmount",
                f".//{ns}AmountSold",
                ".//Amount",
                ".//TotalOfferingAmount",
            ]:
                elem = root.find(path)
                if elem is not None and elem.text:
                    # Parse amount (remove commas, $ signs)
                    amount_str = elem.text.replace(",", "").replace("$", "").strip()
                    try:
                        amount = float(amount_str)
                        if amount > 0:
                            return amount
                    except ValueError:
                        continue
    except ET.ParseError:
        pass

    # Fallback: regex extraction
    patterns = [
        r"<Amount>(\d[\d,]*)</Amount>",
        r"<TotalOfferingAmount>(\d[\d,]*)</TotalOfferingAmount>",
        r"\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, xml_content)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _extract_company_from_xml(xml_content: str) -> Optional[str]:
    """Extract company name from Form D XML."""
    try:
        root = ET.fromstring(xml_content)
        for path in [
            ".//CompanyName",
            ".//IssuerName",
            ".//Name",
        ]:
            elem = root.find(path)
            if elem is not None and elem.text:
                name = elem.text.strip()
                if name and len(name) >= 2:
                    return name
    except ET.ParseError:
        pass

    # Fallback: regex extraction
    patterns = [
        r"<CompanyName>([^<]+)</CompanyName>",
        r"<IssuerName>([^<]+)</IssuerName>",
    ]
    for pattern in patterns:
        match = re.search(pattern, xml_content)
        if match:
            return match.group(1).strip()
    return None


def _fetch_edgar_details(cik: str) -> tuple[float, str]:
    """
    Fetch funding amount and industry group from EDGAR Form D filing.

    Args:
        cik: SEC Central Index Key

    Returns:
        Tuple of (amount_cny, industry_group) — amount converted to CNY (USD × 7.2)
    """
    amount = 0.0
    industry_group = ""

    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }

        # First get the company's recent filings to find Form D
        detail_url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
        response = requests.get(detail_url, headers=headers, timeout=REQUEST_TIMEOUT)

        if response.status_code != 200:
            logger.debug(f"Failed to fetch company filings for CIK {cik}")
            return 0.0, ""

        data = response.json()
        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        accession_numbers = filings.get("accessionNumber", [])

        # Find the most recent D or D/A filing
        d_filing_idx = None
        for i, form in enumerate(forms):
            if form in ["D", "D/A"]:
                d_filing_idx = i
                break

        if d_filing_idx is None:
            logger.debug(f"No Form D filing found for CIK {cik}")
            return 0.0, ""

        # Get the accession number
        acc_no_full = accession_numbers[d_filing_idx]
        acc_no_formatted = acc_no_full.replace("-", "")

        # Build URL for the Form D XML
        base_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc_no_formatted}/"
        xml_url = f"{base_url}primary_doc.xml"

        # Fetch the XML
        xml_response = requests.get(xml_url, headers=headers, timeout=REQUEST_TIMEOUT)
        if xml_response.status_code != 200:
            logger.debug(f"Failed to fetch Form D XML for CIK {cik}")
            return 0.0, ""

        # Parse XML using BeautifulSoup with xml features
        try:
            soup = BeautifulSoup(xml_response.text, 'xml')

            # Find offeringData
            offering_data = soup.find('offeringData')
            if offering_data:
                # Get amount from totalOfferingAmount
                amount_elem = offering_data.find('totalOfferingAmount')
                if amount_elem and amount_elem.string:
                    try:
                        amount = float(amount_elem.string.strip())
                        if amount > 0:
                            logger.debug(f"Found amount ${amount} for CIK {cik}")
                    except ValueError:
                        pass

                # Get industry group
                industry_group_elem = offering_data.find('industryGroup')
                if industry_group_elem:
                    # Try industryGroupType first
                    type_elem = industry_group_elem.find('industryGroupType')
                    if type_elem and type_elem.string:
                        industry_group = type_elem.string.strip()
                        logger.debug(f"Found industry: {industry_group} for CIK {cik}")
                    else:
                        # Look for the selected industry type (boolean tags)
                        for tag in ['technologyAndEquipment', 'biotechnology', 'healthcare',
                                   'finance', 'realEstate', 'energyAndNaturalResources',
                                   'telecommunications', 'mediaAndEntertainment', 'consumerGoods',
                                   'commercialProductsAndServices', 'financialServices',
                                   'insurance', 'investmentFund', 'otherTechnology']:
                            elem = industry_group_elem.find(tag)
                            if elem and elem.string and elem.string.strip().lower() == 'true':
                                industry_group = tag.replace('And', ' & ').replace('consumerGoods', 'Consumer Goods')
                                industry_group = industry_group.replace('telecommunications', 'Telecommunications')
                                industry_group = industry_group.replace('mediaAndEntertainment', 'Media & Entertainment')
                                industry_group = industry_group.replace('commercialProductsAndServices', 'Commercial Products & Services')
                                industry_group = industry_group.replace('financialServices', 'Financial Services')
                                industry_group = industry_group.replace('technologyAndEquipment', 'Technology & Equipment')
                                industry_group = industry_group.replace('biotechnology', 'Biotechnology')
                                industry_group = industry_group.replace('healthcare', 'Healthcare')
                                industry_group = industry_group.replace('realEstate', 'Real Estate')
                                industry_group = industry_group.replace('energyAndNaturalResources', 'Energy & Natural Resources')
                                industry_group = industry_group.replace('investmentFund', 'Investment Fund')
                                industry_group = industry_group.replace('otherTechnology', 'Other Technology')
                                logger.debug(f"Found industry: {industry_group} for CIK {cik}")
                                break

        except Exception as e:
            logger.debug(f"Failed to parse Form D XML for CIK {cik}: {e}")

        return amount * 7.2, industry_group  # Convert USD → CNY

    except Exception as e:
        logger.debug(f"Failed to fetch EDGAR details for CIK {cik}: {e}")
        return 0.0, ""


def _fetch_edgar_amount(cik: str) -> float:
    """Legacy function - returns amount only."""
    amount, _ = _fetch_edgar_details(cik)
    return amount


def fetch_edgar_filings(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    min_amount: float = 250000,  # SEC threshold for Form D
) -> list[FundingEvent]:
    """
    Fetch SEC EDGAR Form D filings for the given date range.

    Args:
        start_date: Start date in YYYY-MM-DD format (default: 30 days ago)
        end_date: End date in YYYY-MM-DD format (default: today)
        min_amount: Minimum funding amount to include in CNY (default: 1,800,000 CNY ≈ $250k USD × 7.2)

    Returns:
        List of FundingEvent objects from EDGAR data
    """
    if not start_date or not end_date:
        start_date, end_date = _get_default_date_range()

    events = []

    try:
        # Search EDGAR for Form D filings
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }

        # EDGAR search API - include Form C, D, and D/A filings
        # Repeat forms= param for each type
        search_url = (
            f"https://efts.sec.gov/LATEST/search-index?"
            f"q=%22Form%20D%22&"
            f"forms=D&forms=D%2FA&forms=C&"
            f"dateRange=custom&"
            f"startdt={start_date}&"
            f"enddt={end_date}"
        )

        logger.info(f"Searching EDGAR: {search_url}")
        response = requests.get(search_url, headers=headers, timeout=REQUEST_TIMEOUT)

        if response.status_code != 200:
            logger.error(f"EDGAR search failed: {response.status_code}")
            return events

        data = response.json()
        hits = data.get("hits", {}).get("hits", [])
        total_val = data.get("hits", {}).get("total", 0)
        # Handle both {"total": 123} and {"total": {"value": 123}} formats
        if isinstance(total_val, dict):
            total = total_val.get("value", 0)
        else:
            total = total_val
        logger.info(f"Found {total} filings, processing {len(hits)}")

        for hit in hits:
            try:
                source = hit.get("_source", {})

                # Extract filing metadata
                ciks = source.get("ciks", [])
                cik = ciks[0] if ciks else ""
                filing_date = source.get("file_date", "")
                display_names = source.get("display_names", [])
                form_type = source.get("form", "")  # C, D, D/A, etc.
                
                if not display_names:
                    continue
                
                # Only process Form C, D, D/A
                if form_type not in ("C", "D", "D/A"):
                    continue

                # Extract company name from display name
                # Format: "COMPANY NAME (CIK 0001234567)"
                company_name = display_names[0].split(" (CIK")[0].strip()

                # Skip if not a valid company name
                if not company_name or len(company_name) < 2:
                    continue

                # Skip if it looks like an investment fund
                if _is_likely_fund(company_name):
                    logger.debug(f"Skipping fund: {company_name}")
                    continue

                # Try to fetch amount and industry from detailed filing
                amount, industry_group = _fetch_edgar_details(cik)

                # Skip if amount is too small
                if amount > 0 and amount < MIN_STARTUP_AMOUNT:
                    logger.debug(f"Skipping small amount: {company_name} ${amount:,.0f}")
                    continue

                # Parse date
                announcement_date = _parse_edgar_date(filing_date)

                # Estimate round from amount (Form D doesn't have round type)
                if amount > 0:
                    round_type = _estimate_startup_round(amount)
                else:
                    round_type = "Seed"  # Default for Form D without amount

                event = FundingEvent(
                    company_name=company_name,
                    company_domain="",  # EDGAR doesn't provide domain
                    round_type=round_type,
                    amount_cny=amount,
                    industry_group=industry_group,
                    announcement_date=announcement_date,
                    investors="",
                    source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                    source="edgar",
                )
                events.append(event)
                logger.debug(f"Parsed EDGAR: {company_name} {round_type} ${amount:,.0f}")

            except Exception as e:
                logger.error(f"Failed to parse EDGAR filing: {e}")
                continue

        logger.info(f"Parsed {len(events)} EDGAR funding events")

    except requests.exceptions.RequestException as e:
        logger.error(f"EDGAR request failed: {e}")
    except Exception as e:
        logger.error(f"EDGAR parsing failed: {e}")

    return events


def get_edgar_filing_details(cik: str, accession_number: str) -> dict:
    """
    Fetch detailed Form D filing data from EDGAR.

    Args:
        cik: SEC Central Index Key
        accession_number: Filing accession number

    Returns:
        Dictionary with filing details
    """
    details = {
        "company_name": "",
        "amount": 0,
        "date": None,
        "state": "",
        "industry": "",
        "investors": [],
    }

    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        }

        # Fetch the filing document
        # EDGAR URL format for Form D
        url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?"
            f"action=getcompany&"
            f"CIK={cik}&"
            f"type=Form%20D&"
            f"dateb=&owner=include&"
            f"count=1"
        )

        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            # Try to extract amount from response
            content = response.text

            # Look for Form D XML link
            xml_match = re.search(r'href="([^"]*\.xml[^"]*)"', content)
            if xml_match:
                xml_url = xml_match.group(1)
                if not xml_url.startswith("http"):
                    xml_url = "https://www.sec.gov" + xml_url

                # Fetch XML
                xml_response = requests.get(xml_url, headers=headers, timeout=REQUEST_TIMEOUT)
                if xml_response.status_code == 200:
                    xml_content = xml_response.text
                    details["amount"] = _extract_amount_from_xml(xml_content)
                    details["company_name"] = _extract_company_from_xml(xml_content)

    except Exception as e:
        logger.error(f"Failed to fetch EDGAR details: {e}")

    return details


def fetch_edgar_filings_simple(days: int = 30, min_amount: float = 250000) -> list[FundingEvent]:
    """
    Simple EDGAR Form D fetcher that works with current SEC API.

    Args:
        days: Number of days to look back
        min_amount: Minimum funding amount

    Returns:
        List of FundingEvent objects
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    return fetch_edgar_filings(
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        min_amount=min_amount,
    )
