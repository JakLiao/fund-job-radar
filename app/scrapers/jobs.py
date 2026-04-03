"""Job postings scraper — Phase 2.

通过搜索引擎查找公司的公开招聘数据。

数据来源：
1. Google 搜索结果摘要
2. 公司 LinkedIn 页面（公开）
3. Indeed/Glassdoor 等招聘平台（公开职位）
4. 公司官网 Careers 页面（Playwright 抓取）

注意：大多数招聘平台需要登录才能看到详细职位，
这里主要获取公开可见的招聘信息摘要。
"""

import logging
import re
import time
from typing import Optional

import requests
from datetime import datetime

from ..models import JobPosting

logger = logging.getLogger(__name__)

# Request headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

REQUEST_TIMEOUT = 15


def _clean_company_name(company_name: str) -> str:
    """Clean company name for search."""
    # Remove common suffixes
    name = re.sub(r',?\s*(LLC|LLP|Inc|Corp|Corporation|Ltd|L\.P\.|LP)\.?$', '', company_name, flags=re.IGNORECASE)
    return name.strip()


# Known Greenhouse board slugs for major companies
# Format: lowercase board slug -> company name patterns
_GREENHOUSE_BOARD_MAP = {
    # AI Labs
    "openai": ["openai"],
    "anthropic": ["anthropic", "anthropic ai"],
    "google": ["google", "alphabet"],
    "mistral": ["mistral ai", "mistral"],
    "cohere": ["cohere", "cohere ai"],
    "inflection": ["inflection", "inflection ai"],
    "adept": ["adept", "adept ai"],
    "runway": ["runway", "runway ml"],
    "pika": ["pika", "pika labs"],
    "heygen": ["heygen", "heygen inc"],
    "characterai": ["character ai", "character.ai"],
    "ai21": ["ai21", "ai21 labs", "ai21labs"],
    # AI Infrastructure
    "scale": ["scale ai", "scale, inc."],
    "labelbox": ["labelbox", "label box"],
    "snorkel": ["snorkel", "snorkel ai"],
    "replicate": ["replicate"],
    "huggingface": ["hugging face", "huggingface"],
    "together": ["together ai", "together"],
    "anyscale": ["anyscale", "any-scale"],
    "clarifai": ["clarifai"],
    # Developer Tools
    "vercel": ["vercel"],
    "supabase": ["supabase"],
    "railway": ["railway"],
    "render": ["render", "render com"],
    "flyio": ["fly.io", "flyio"],
    "planetscale": ["planetscale", "planet scale"],
    "neon": ["neon", "neon database"],
    "turso": ["turso"],
    "convex": ["convex"],
    # Productivity
    "notion": ["notion", "notion labs"],
    "linear": ["linear", "linear app"],
    "asana": ["asana"],
    "coda": ["coda", "coda.io"],
    "loom": ["loom", "loom video"],
    "miro": ["miro"],
    "monday": ["monday", "monday.com"],
    # Design
    "figma": ["figma"],
    "canva": ["canva", "canva pty"],
    "framer": ["framer"],
    "webflow": ["webflow"],
    # Payments & Finance
    "stripe": ["stripe", "stripe, inc."],
    "circleci": ["circleci"],
    "plaid": ["plaid"],
    "ramp": ["ramp"],
    "mercury": ["mercury", "mercury bank"],
    # Data & Analytics
    "databricks": ["databricks", "databricks, inc."],
    "snowflake": ["snowflake", "snowflake inc."],
    "datadog": ["datadog", "datadog, inc."],
    "elastic": ["elastic", "elastic nv"],
    "grafana": ["grafana"],
    # Security
    "cloudflare": ["cloudflare", "cloudflare, inc."],
    "gitguardian": ["gitguardian"],
    "snyk": ["snyk"],
    "1password": ["1password", "1password"],
    "bitwarden": ["bitwarden"],
    # Crypto
    "coinbase": ["coinbase", "coinbase, inc."],
    "ripple": ["ripple", "ripple labs"],
    "polygon": ["polygon", "polygon technology"],
    "alchemy": ["alchemy", "alchemy api"],
    # Other Tech
    "atlassian": ["atlassian"],
    "twilio": ["twilio", "twilio, inc."],
    "gitlab": ["gitlab"],
    "paloaltonetworks": ["palo alto networks"],
    "airtable": ["airtable"],
    "zapier": ["zapier"],
    "make": ["make", "make (integromat)"],
    "intercom": ["intercom"],
    # Automotive / Mobility
    "aurora": ["aurora", "aurora innovation"],
    "nuro": ["nuro", "nuro, inc."],
    "ford": ["ford motor", "ford motor company"],
    "gm": ["general motors", "gm"],
    "toyota": ["toyota", "toyota motor"],
    "ike": ["ike", "ike american"],
    # Healthcare
    "aurora-health": ["aurora health care"],
    # Misc
    "tanium": ["tanium"],
    "grab": ["grab", "grab holdings"],
    "gojek": ["gojek", "gojek tokopedia"],
}

# Chinese company job sources - career page URLs and known ATS
# Format: company_name_pattern -> (career_url, source_tag)
_CN_COMPANY_CAREER_MAP = {
    "字节跳动": ("https://jobs.bytedance.com", "liepin"),
    "阿里巴巴": ("https://talent.alibaba.com", "liepin"),
    "腾讯": ("https://careers.tencent.com", "liepin"),
    "百度": ("https://talent.baidu.com", "liepin"),
    "京东": ("https://careers.jd.com", "liepin"),
    "美团": ("https://careers.meituan.com", "liepin"),
    "拼多多": ("https://www.pinduoduo.com", "liepin"),
    "小米": ("https://xiaomi.jobs.huoric.com", "liepin"),
    "华为": ("https://career.huawei.com", "liepin"),
    "滴滴": ("https://www.didiglobal.com/careers", "liepin"),
    "快手": ("https://zhaopin.kuaishou.cn", "liepin"),
    "网易": ("https://hr.163.com", "liepin"),
    "哔哩哔哩": ("https://www.bilibili.com", "liepin"),
    "小红书": ("https://www.xiaohongshu.com", "liepin"),
    "商汤": ("https://www.sensetime.com", "liepin"),
    "旷视": ("https://www.megvii.com", "liepin"),
    "依图": ("https://www.yitutech.com", "liepin"),
    "Momenta": ("https://www.momenta.cn", "liepin"),
    "小马智行": ("https://www.pony.ai", "liepin"),
    "文远知行": ("https://www.weride.ai", "liepin"),
    "元戎启行": ("https://www.deeproute.ai", "liepin"),
    "轻舟智航": ("https://www.qcraft.ai", "liepin"),
    "理想汽车": ("https://careers.ideal.cn", "liepin"),
    "蔚来": ("https://www.nio.cn/careers", "liepin"),
    "小鹏汽车": ("https://careers.xpeng.cn", "liepin"),
    "毫末智行": ("https://www.haomo.ai", "liepin"),
    "地平线机器人": ("https://www.horizon.ai", "liepin"),
    "芯驰科技": ("https://www.semidrive.com", "liepin"),
    "黑芝麻智能": ("https://www.blacksesame.com.cn", "liepin"),
    "图达通": ("https://www.sensegrow.com", "liepin"),
    "速腾聚创": ("https://www.robosense.cn", "liepin"),
    "禾赛科技": ("https://www.hesaitech.com", "liepin"),
    "大疆": ("https://www.dji.com/careers", "liepin"),
    "科沃斯": ("https://www.ecovacs.cn", "liepin"),
    "石头科技": ("https://www.roborock.com", "liepin"),
    "云鲸智能": ("https://www.yunji.com", "liepin"),
    "追觅": ("https://www.dreamtech.com", "liepin"),
    "极米科技": ("https://www.xgimi.com", "liepin"),
    "蔚来资本": ("https://www.nio.cn/capital", "liepin"),
    "小马智行": ("https://www.pony.ai/careers", "liepin"),
    "AutoX": ("https://www.autox.ai", "liepin"),
    "Waymo": ("https://waymo.com/careers", "liepin"),
    "Pony.ai": ("https://www.pony.ai", "liepin"),
    "WeRide": ("https://www.weride.ai", "liepin"),
    "DeepRoute": ("https://www.deeproute.ai", "liepin"),
    "Momenta": ("https://www.momenta.cn", "liepin"),
    "Horizon Robotics": ("https://www.horizon.ai", "liepin"),
    "Cambricon": ("https://www.cambricon.com", "liepin"),
    "Cambricon Tech": ("https://www.cambricon.com", "liepin"),
    "寒武纪": ("https://www.cambricon.com", "liepin"),
    "地平线": ("https://www.horizon.ai", "liepin"),
    "商汤科技": ("https://www.sensetime.com", "liepin"),
    "旷视科技": ("https://www.megvii.com", "liepin"),
    "依图科技": ("https://www.yitutech.com", "liepin"),
    "云从科技": ("https://www.cloudwalk.com", "liepin"),
    "格林深瞳": ("https://www.deepglint.com", "liepin"),
    "创新奇智": ("https://www.ai-achar.com", "liepin"),
    "第四范式": ("https://www.4paradigm.com", "liepin"),
    "九号公司": ("https://www.ninebot.com", "liepin"),
    "石头世纪": ("https://www.roborock.com", "liepin"),
    "九号机器人": ("https://www.ninebot.com", "liepin"),
    "普渡科技": ("https://www.pudutech.com", "liepin"),
    "擎朗智能": ("https://www.keenon.com", "liepin"),
    "猎户星空": ("https://www.orionstar.com", "liepin"),
    "思必驰": ("https://www.aispeech.com", "liepin"),
    "云知声": ("https://www.unisound.com", "liepin"),
    "出门问问": ("https://www.chumenwenwen.com", "liepin"),
    "声智科技": ("https://www.soundai.com", "liepin"),
    "若琪": ("https://www.rokid.com", "liepin"),
    "百度Apollo": ("https://apollo.jd.com", "liepin"),
    "小马智行": ("https://www.pony.ai", "liepin"),
    "文远知行": ("https://www.weride.ai", "liepin"),
    "AutoX": ("https://www.autox.ai", "liepin"),
}


def _is_chinese_company(company_name: str) -> bool:
    """Check if a company name appears to be a Chinese company."""
    if not company_name:
        return False
    
    # Chinese characters present
    if re.search(r'[\u4e00-\u9fa5]', company_name):
        return True
    
    # Known English-name Chinese companies
    known_cn = [
        'bytedance', 'alibaba', 'tencent', 'baidu', 'jd.com', 'meituan',
        'pinduoduo', 'xiaomi', 'huawei', 'didi', 'kuaishou', 'netease',
        'bilibili', 'xiaohongshu', 'sensetime', 'megvii', 'yitutech',
        'momenta', 'pony', 'weride', 'deeproute', 'qcraft', 'idealauto',
        'nioinc', 'nio', 'xpeng', 'haomo', 'horizonrobotics', 'horizon',
        'semidrive', 'blacksesame', 'sensegrow', 'robosense', 'hesaitech',
        'dji', 'ecovacs', 'roborock', 'yunji', 'dreamtech', 'xgimi',
        'autox', 'waymo', 'cambricon', 'deepglint', 'ai-achar', '4paradigm',
        'ninebot', 'pudutech', 'keenon', 'orionstar', 'aispeech', 'unisound',
        'rokid', 'apolloauto', 'apollo', 'cloudwalk', 'minimax', 'moonshot',
        'zhipuai', 'stepfun', 'tiangong', 'galbot', 'unitree', 'keyi',
        'langchain', 'zhipin', 'kuaishou',
    ]
    
    clean = company_name.lower().replace(' ', '').replace('-', '').replace('.', '')
    return any(k in clean for k in known_cn)


def _get_cn_career_url(company_name: str) -> tuple:
    """Get career page URL for a Chinese company."""
    # Direct match
    for cn_name, (url, src) in _CN_COMPANY_CAREER_MAP.items():
        if cn_name.lower() in company_name.lower() or company_name.lower() in cn_name.lower():
            return (url, src)
    
    # Try to construct from name
    clean = re.sub(r'[\s\-,.。]+', '', company_name)
    
    # Try common patterns
    patterns = [
        f"https://careers.{clean.lower()}.com",
        f"https://jobs.{clean.lower()}.com",
        f"https://talent.{clean.lower()}.com",
        f"https://hr.{clean.lower()}.com",
        f"https://career.{clean.lower()}.com",
        f"https://www.{clean.lower()}.com/careers",
        f"https://www.{clean.lower()}.com/job",
    ]
    
    return (patterns[0], "careers")


class PlaywrightContext:
    """Context manager for Playwright browser lifecycle — eliminates duplicate cleanup code."""

    def __init__(self, timeout: int = 30000):
        self.timeout = timeout
        self.playwright = None
        self.browser = None
        self.page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-images',
            ],
        )
        context = self.browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ),
        )
        self.page = context.new_page()
        self.page.set_default_timeout(self.timeout)
        # Block images and fonts to speed up
        self.page.route('**/*.{png,jpg,jpeg,gif,svg,ico,webp}', lambda route: route.abort())
        self.page.route('**/*.woff*', lambda route: route.abort())
        return self.page, self.browser, self.playwright

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
        return False  # don't suppress exceptions


def _fetch_cn_careers_page(company_name: str, career_url: str = "") -> list[JobPosting]:
    """
    Fetch job postings from Chinese company career pages.
    
    Uses Playwright for JavaScript-rendered pages.
    
    Args:
        company_name: Company name
        career_url: Known career page URL (optional)
    
    Returns:
        List of JobPosting objects
    """
    postings = []
    
    if not career_url:
        career_url, _ = _get_cn_career_url(company_name)
    
    if not career_url:
        return []
    
    try:
        with PlaywrightContext() as (page, browser, playwright):
            response = page.goto(career_url, wait_until='domcontentloaded')
            if response is None or response.status >= 400:
                logger.debug(f"  CN careers: no response from {career_url}")
                return []

            time.sleep(3)  # Wait for JS rendering

            # Try to find job count
            job_count = 0
            job_titles = []
            job_urls = []

            # Look for common job count patterns in Chinese
            count_selectors = [
                '[class*="count"]',
                '[class*="open"]',
                '[class*="position"]',
                '[class*="job"]',
                '[data-testid*="count"]',
            ]

            for selector in count_selectors:
                try:
                    elements = page.query_selector_all(selector)
                    for el in elements:
                        text = el.inner_text()
                        nums = re.findall(r'(\d+)\s*(?:个)?\s*(?:职位|岗位|招聘|open|position)', text, re.IGNORECASE)
                        if nums:
                            job_count = max(job_count, int(nums[0]))
                except Exception:
                    pass

            # Look for job listings
            link_selectors = [
                'a[href*="/jobs/"]',
                'a[href*="/careers/"]',
                'a[href*="/job/"]',
                'a[href*="/position/"]',
                '[class*="job-card"] a',
                '[class*="job-listing"] a',
                'article a',
            ]

            found_jobs = set()
            for selector in link_selectors:
                try:
                    links = page.query_selector_all(selector)
                    for link in links:
                        title = link.inner_text().strip()
                        href = link.get_attribute('href') or ''

                        if len(title) < 4 or len(title) > 150:
                            continue
                        if not title or title in found_jobs:
                            continue
                        skip = ['learn more', 'read more', 'apply', 'view all',
                                'submit', 'contact', 'about', 'blog', 'home',
                                '更多', '查看全部', '申请', '详情']
                        if any(w in title.lower() for w in skip) and len(title) < 20:
                            continue

                        found_jobs.add(title)
                        if href.startswith('/'):
                            from urllib.parse import urljoin
                            href = urljoin(career_url, href)
                        elif not href.startswith('http'):
                            href = urljoin(career_url, href)

                        job_titles.append(title)
                        job_urls.append(href)
                except Exception:
                    pass

            if len(found_jobs) > job_count:
                job_count = len(found_jobs)

            logger.info(f"  CN careers page {career_url}: found {job_count} jobs, {len(job_titles)} titles")

            # Create postings
            if job_count > 0:
                if job_titles:
                    for i, (title, url) in enumerate(zip(job_titles[:20], job_urls[:20])):
                        posting = JobPosting(
                            company_name=company_name,
                            job_title=title if len(title) < 100 else title[:97] + '...',
                            posting_date=datetime.now(),
                            source="careers",
                            job_count=1,
                        )
                        postings.append(posting)
                    remaining = job_count - len(job_titles)
                    if remaining > 0:
                        postings.append(JobPosting(
                            company_name=company_name,
                            job_title=f"Open Positions ({job_count} total, +{remaining} more)",
                            posting_date=datetime.now(),
                            source="careers",
                            job_count=remaining,
                        ))
                else:
                    postings.append(JobPosting(
                        company_name=company_name,
                        job_title=f"Open Positions ({job_count})",
                        posting_date=datetime.now(),
                        source="careers",
                        job_count=job_count,
                    ))

    except ImportError:
        logger.debug("Playwright not installed, skipping CN careers page fetch")
    except Exception as e:
        logger.debug(f"  CN careers fetch failed for {career_url}: {e}")

    return postings


def _search_lagou_api(company_name: str) -> list[JobPosting]:
    """
    Search Lagou (拉勾) for company jobs using their API.
    
    Note: Lagou requires JS rendering for most pages. We try their API endpoint.
    
    Args:
        company_name: Company name
    
    Returns:
        List of JobPosting objects
    """
    postings = []
    
    try:
        url = f"https://www.lagou.com/jobs/positionAjax.json?needAddtionalResult=false&isSchoolJob=0&pn=1&kd={requests.utils.quote(company_name)}"
        response = requests.get(
            url,
            headers={
                **HEADERS,
                "Referer": "https://www.lagou.com/",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT,
        )
        
        if response.status_code == 200:
            try:
                data = response.json()
                if data.get('success'):
                    result = data.get('content', {})
                    positions = result.get('positionResult', {}).get('result', [])
                    total_count = result.get('positionResult', {}).get('total', len(positions))
                    
                    logger.info(f"  Lagou API: found {total_count} jobs for {company_name}")
                    
                    if positions:
                        for pos in positions[:20]:
                            posting = JobPosting(
                                company_name=company_name,
                                job_title=pos.get('positionName', 'Unknown'),
                                posting_date=datetime.now(),
                                source="lagou",
                                job_count=1,
                            )
                            postings.append(posting)
                        
                        if total_count > len(positions):
                            postings.append(JobPosting(
                                company_name=company_name,
                                job_title=f"Open Positions ({total_count} total)",
                                posting_date=datetime.now(),
                                source="lagou",
                                job_count=total_count - len(positions),
                            ))
            except (ValueError, KeyError) as e:
                logger.debug(f"  Lagou API parse error: {e}")
        else:
            logger.debug(f"  Lagou API: status {response.status_code}")
            
    except Exception as e:
        logger.debug(f"  Lagou API search failed: {e}")
    
    return postings


def _search_liepin(company_name: str) -> list[JobPosting]:
    """
    Search Liepin (猎聘) for company jobs.
    
    Note: liepin.com is often blocked (404 on search pages).
    We try their specific company URL if known.
    
    Args:
        company_name: Company name
    
    Returns:
        List of JobPosting objects
    """
    postings = []
    
    # Try direct company URL on liepin
    slug = re.sub(r'[\s\-,.。]+', '', company_name).lower()
    url = f"https://www.liepin.com/company/{slug}/"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.encoding = response.apparent_encoding or 'utf-8'
        
        if response.status_code == 200 and len(response.text) > 5000:
            # Look for job count
            counts = re.findall(r'(\d+)\s*个职位', response.text)
            if counts:
                total = int(counts[0])
                logger.info(f"  Liepin: found {total} jobs for {company_name}")
                postings.append(JobPosting(
                    company_name=company_name,
                    job_title=f"Open Positions ({total})",
                    posting_date=datetime.now(),
                    source="liepin",
                    job_count=total,
                ))
            else:
                # Try to find job titles
                titles = re.findall(r'<a[^>]+title="([^"]+)"[^>]*>([^<]{4,80}<?[^<]*职位[^>]*>[^<]*)</a>', response.text, re.IGNORECASE)
                if titles:
                    for _, title in titles[:20]:
                        posting = JobPosting(
                            company_name=company_name,
                            job_title=title.strip(),
                            posting_date=datetime.now(),
                            source="liepin",
                            job_count=1,
                        )
                        postings.append(posting)
                else:
                    logger.debug(f"  Liepin: no jobs found for {company_name}")
        else:
            logger.debug(f"  Liepin: status {response.status_code} for {company_name}")
            
    except Exception as e:
        logger.debug(f"  Liepin search failed for {company_name}: {e}")
    
    return postings


def _search_zhaopin(company_name: str) -> list[JobPosting]:
    """
    Search Zhilian (智联招聘) for company jobs.
    
    Note: Zhilian has CAPTCHA protection for search pages.
    We try direct company search URL.
    
    Args:
        company_name: Company name
    
    Returns:
        List of JobPosting objects
    """
    postings = []
    
    # Try to find company on zhilian
    url = f"https://sou.zhaopin.com/?jl=&kw={requests.utils.quote(company_name)}"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.encoding = response.apparent_encoding or 'utf-8'
        
        if response.status_code == 200 and len(response.text) > 5000:
            # Look for job count in response
            counts = re.findall(r'(\d+)\s*(?:个职位|个岗位)', response.text)
            if counts:
                total = int(counts[0])
                logger.info(f"  Zhilian: found {total} jobs for {company_name}")
                postings.append(JobPosting(
                    company_name=company_name,
                    job_title=f"Open Positions ({total})",
                    posting_date=datetime.now(),
                    source="zhaopin",
                    job_count=total,
                ))
            else:
                logger.debug(f"  Zhilian: no jobs found for {company_name}")
        else:
            logger.debug(f"  Zhilian: status {response.status_code} for {company_name}")
            
    except Exception as e:
        logger.debug(f"  Zhilian search failed for {company_name}: {e}")
    
    return postings


def _slugify_company(company_name: str) -> str:
    """Convert company name to likely Greenhouse board slug."""
    clean = _clean_company_name(company_name)
    # Remove common suffixes
    clean = re.sub(r'[,.\s]+', '', clean).lower()
    # Handle specific known patterns
    slug_map = {
        "pacegenix": "pacegenix",
        "anthropic": "anthropic",
        "openai": "openai",
        "stripe": "stripe",
    }
    if clean.lower() in slug_map:
        return slug_map[clean.lower()]
    # Default: just lowercase and remove spaces
    return clean.lower().replace(' ', '')


def _search_greenhouse(company_name: str) -> list[JobPosting]:
    """
    Search for jobs using Greenhouse.io public API.
    
    Greenhouse is an ATS (Applicant Tracking System) used by many tech companies.
    Their public API returns job listings without authentication.
    
    Args:
        company_name: Name of the company
    
    Returns:
        List of JobPosting objects with job counts and titles
    """
    postings = []
    
    # Check board map first
    clean_lower = _clean_company_name(company_name).lower()
    board_slug = None
    
    # Try direct board map lookup
    for slug, names in _GREENHOUSE_BOARD_MAP.items():
        if clean_lower in names or clean_lower.replace(' ', '') in names:
            board_slug = slug
            break
    
    # If not found in map, try slugify
    if board_slug is None:
        guessed_slug = _slugify_company(company_name)
        # Try the guessed slug
        board_slug = guessed_slug
    
    if not board_slug:
        return []
    
    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_slug}/jobs?content=true"
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            jobs = data.get("jobs", [])
            logger.info(f"  Greenhouse: found {len(jobs)} jobs for {company_name}")
            
            if jobs:
                # Create individual postings for each job (or summary)
                # For efficiency, create one summary posting with total count
                # and optionally a few sample titles
                from datetime import datetime
                
                # Get total count
                total_count = len(jobs)
                
                # Get sample job titles (up to 5)
                sample_titles = [j.get("title", "Unknown") for j in jobs[:5]]
                
                if total_count > 0:
                    # Create a summary posting
                    posting = JobPosting(
                        company_name=company_name,
                        job_title=f"Open Positions ({total_count})",
                        posting_date=datetime.now(),
                        source="greenhouse",
                        job_count=total_count,
                    )
                    postings.append(posting)
                    logger.info(f"  Greenhouse summary: {total_count} positions")
                    
        elif response.status_code == 404:
            logger.debug(f"  Greenhouse: no board found for {company_name} (slug={board_slug})")
        else:
            logger.debug(f"  Greenhouse: {response.status_code} for {company_name}")
            
    except Exception as e:
        logger.debug(f"  Greenhouse search failed for {company_name}: {e}")
    
    return postings


def _search_ddg_jobs(query: str) -> list[dict]:
    """
    Search for jobs using DuckDuckGo.
    
    Args:
        query: Search query
    
    Returns:
        List of job result dictionaries
    """
    results = []
    try:
        url = f"https://duckduckgo.com/html/?q={requests.utils.quote(query)}"
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            # Parse results
            # Look for job-related snippets
            import re
            # Find job counts
            job_count_pattern = r'(\d+)\s+(?:openings?|jobs?|positions?)'
            matches = re.findall(job_count_pattern, response.text, re.IGNORECASE)
            results = [{"count": int(m)} for m in matches[:5]]
                
    except Exception as e:
        logger.debug(f"DuckDuckGo search failed: {e}")
    
    return results


def _fetch_linkedin_company(company_name: str) -> dict:
    """
    Fetch LinkedIn company page for job information.
    
    Args:
        company_name: Company name
    
    Returns:
        Dictionary with company info and job openings
    """
    info = {
        "company_name": company_name,
        "linkedin_url": "",
        "job_openings_count": 0,
        "hiring_since": "",
        "industries": [],
    }
    
    try:
        # Try direct LinkedIn company URL
        clean_name = _clean_company_name(company_name)
        slug = clean_name.lower().replace(' ', '-').replace('.', '').replace(',', '')
        
        # Direct LinkedIn company page
        linkedin_url = f"https://www.linkedin.com/company/{slug}"
        
        response = requests.get(linkedin_url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        
        if response.status_code == 200 and 'LinkedIn' in response.text:
            info["linkedin_url"] = response.url
            logger.debug(f"Found LinkedIn: {info['linkedin_url']}")
            
            # Try to find job count in page
            job_pattern = r'(\d+[\d,]*)\s+(?:job openings?|open positions)'
            job_matches = re.findall(job_pattern, response.text, re.IGNORECASE)
            if job_matches:
                count_str = job_matches[0].replace(',', '')
                info["job_openings_count"] = int(count_str)
                logger.debug(f"Found {info['job_openings_count']} jobs")
                
    except Exception as e:
        logger.debug(f"LinkedIn fetch failed: {e}")
    
    return info


def _fetch_indeed_company(company_name: str) -> dict:
    """
    Fetch Indeed company page for job information.
    
    Args:
        company_name: Company name
    
    Returns:
        Dictionary with company job info
    """
    info = {
        "company_name": company_name,
        "indeed_jobs_url": "",
        "open_positions": 0,
    }
    
    try:
        clean_name = _clean_company_name(company_name)
        
        # Use DuckDuckGo to search for Indeed company page
        search_query = f"{clean_name} site:indeed.com/cmp"
        search_url = f"https://duckduckgo.com/html/?q={requests.utils.quote(search_query)}"
        
        response = requests.get(search_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            # Find Indeed company URL
            url_pattern = r'indeed\.com/cmp/[\w-]+'
            matches = re.findall(url_pattern, response.text)
            if matches:
                url = matches[0].rstrip('/')
                info["indeed_jobs_url"] = f"https://www.{url}"
                logger.debug(f"Found Indeed: {info['indeed_jobs_url']}")
                
            # Try to find job openings count
            count_pattern = r'(\d+)\s+(?:openings?|positions?)'
            count_matches = re.findall(count_pattern, response.text, re.IGNORECASE)
            if count_matches:
                info["open_positions"] = int(count_matches[0])
                
    except Exception as e:
        logger.debug(f"Indeed fetch failed: {e}")
    
    return info


def _search_jobs_ddg(query: str) -> list[dict]:
    """
    Search for jobs using DuckDuckGo.
    
    Args:
        query: Search query
    
    Returns:
        List of job results
    """
    results = []
    try:
        url = f"https://duckduckgo.com/html/?q={requests.utils.quote(query)}"
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            # Parse job listings from DuckDuckGo HTML results
            import re
            
            # Extract job titles and companies from search results
            title_pattern = r'<a class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]+)</a>'
            matches = re.findall(title_pattern, response.text)
            
            for href, title in matches[:10]:
                results.append({
                    "title": title.strip(),
                    "url": href
                })
            
    except Exception as e:
        logger.debug(f"DuckDuckGo search failed: {e}")
    
    return results


def _construct_domain_from_name(company_name: str) -> str:
    """
    Construct likely domain from company name.
    
    Args:
        company_name: Company name
    
    Returns:
        Likely domain (e.g., "pacegenix.com", "www.pacegenix.com")
    """
    # Clean company name
    clean = re.sub(r'[,.\s]+', '-', _clean_company_name(company_name))
    clean = re.sub(r'[^a-zA-Z0-9\-]', '', clean)
    clean = clean.strip('-').lower()
    
    # Common patterns
    patterns = [
        f"{clean}.com",
        f"www.{clean}.com",
    ]
    
    return patterns[0]  # Return primary guess


def _fetch_company_careers_page(company_name: str, company_domain: str = "") -> list[JobPosting]:
    """
    Fetch job postings by scraping the company's official careers page using Playwright.
    
    Tries multiple URL patterns:
    - {domain}/careers
    - {domain}/jobs
    - {domain}/about/careers
    - {domain}/careers/jobs
    
    Args:
        company_name: Company name
        company_domain: Company website domain (e.g., "stripe.com")
    
    Returns:
        List of JobPosting objects with source='careers'
    """
    postings = []
    
    # Determine domain to use
    if not company_domain:
        company_domain = _construct_domain_from_name(company_name)
    
    # Normalize domain
    domain = company_domain.strip().lower()
    domain = re.sub(r'^https?://', '', domain)
    domain = re.sub(r'^www\.', '', domain)
    domain = domain.rstrip('/')
    
    if not domain:
        return []
    
    # URL patterns to try
    url_patterns = [
        f"https://{domain}/careers",
        f"https://{domain}/jobs",
        f"https://{domain}/about/careers",
        f"https://{domain}/careers/jobs",
        f"https://www.{domain}/careers",
        f"https://www.{domain}/jobs",
    ]
    
    # Deduplicate
    seen = set()
    unique_urls = []
    for url in url_patterns:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    
    try:
        with PlaywrightContext() as (page, browser, playwright):
            for base_url in unique_urls:
                try:
                    logger.debug(f"Trying careers URL: {base_url}")
                    response = page.goto(base_url, wait_until='domcontentloaded')
                
                    if response is None or response.status >= 400:
                        logger.debug(f"  No response from {base_url}")
                        continue
                
                    # Wait a bit for dynamic content
                    time.sleep(2)
                
                    # Try to extract job count
                    job_count = 0
                    job_titles = []
                    job_urls = []
                
                    # Strategy 1: Look for job count badge/text
                    # Patterns: "23 open positions", "We have 15 jobs", "45 openings"
                    count_selectors = [
                        '[class*="count"]',
                        '[class*="openings"]',
                        '[class*="positions"]',
                        '[class*="jobs-count"]',
                        '[data-testid*="count"]',
                        '[data-testid*="opening"]',
                    ]
                
                    for selector in count_selectors:
                        try:
                            elements = page.query_selector_all(selector)
                            for el in elements:
                                text = el.inner_text()
                                # Look for number patterns
                                nums = re.findall(r'(\d+)\s*(?:open\s+)?(?:position|job|opening)', text, re.IGNORECASE)
                                if nums:
                                    job_count = max(job_count, int(nums[0]))
                                    if job_count > 0:
                                        break
                        except Exception:
                            pass
                    if job_count > 0:
                        logger.debug(f"  Found job count badge: {job_count}")
                
                    # Strategy 2: Extract job titles and links from list/card structures
                    # Look for common job listing containers
                    job_link_selectors = [
                        'a[href*="/jobs/"]',
                        'a[href*="/careers/"]',
                        'a[href*="/job/"]',
                        '[class*="job-card"] a',
                        '[class*="job-listing"] a',
                        '[class*="opening"] a',
                        '[class*="position"] a',
                        'article a',
                        '.jobs a',
                        '.careers a',
                    ]
                
                    found_jobs = set()
                    for selector in job_link_selectors:
                        try:
                            links = page.query_selector_all(selector)
                            for link in links:
                                title = link.inner_text().strip()
                                href = link.get_attribute('href') or ''
                            
                                # Filter out non-job links
                                if len(title) < 5 or len(title) > 150:
                                    continue
                                if not title or title in found_jobs:
                                    continue
                                # Skip navigation/footer links
                                skip_words = ['learn more', 'read more', 'apply now', 'view all', 
                                             'submit', 'contact', 'about', 'blog', 'home']
                                if any(w in title.lower() for w in skip_words) and len(title) < 30:
                                    continue
                            
                                found_jobs.add(title)
                            
                                # Resolve relative URLs
                                if href.startswith('/'):
                                    from urllib.parse import urljoin
                                    href = urljoin(base_url, href)
                                elif not href.startswith('http'):
                                    href = urljoin(base_url, href)
                            
                                job_titles.append(title)
                                job_urls.append(href)
                        except Exception:
                            pass
                
                    if len(found_jobs) > job_count:
                        job_count = len(found_jobs)
                
                    if job_count > 0 or job_titles:
                        logger.info(f"  Careers page {base_url}: found {job_count} jobs, {len(job_titles)} titles")
                        break  # Got data, stop trying other URLs
                    
                except Exception as e:
                    logger.debug(f"  Failed to fetch {base_url}: {e}")
                    continue
        
        # If we found jobs, create postings
        if job_count > 0:
            if job_titles:
                # Create individual postings with URLs in title for traceability
                for i, (title, url) in enumerate(zip(job_titles[:20], job_urls[:20])):
                    # Include URL in title for traceability (up to field width limit)
                    display_title = title if len(title) < 100 else title[:97] + '...'
                    posting = JobPosting(
                        company_name=company_name,
                        job_title=f"{display_title}",
                        posting_date=datetime.now(),
                        source="careers",
                        job_count=1,
                    )
                    postings.append(posting)
                
                # If there are more jobs than we captured, add a summary
                remaining = job_count - len(job_titles)
                if remaining > 0:
                    summary = JobPosting(
                        company_name=company_name,
                        job_title=f"Open Positions ({job_count} total, +{remaining} more)",
                        posting_date=datetime.now(),
                        source="careers",
                        job_count=remaining,
                    )
                    postings.append(summary)
            else:
                # Only count, no titles - create summary
                posting = JobPosting(
                    company_name=company_name,
                    job_title=f"Open Positions ({job_count})",
                    posting_date=datetime.now(),
                    source="careers",
                    job_count=job_count,
                )
                postings.append(posting)
        
    except ImportError:
        logger.debug("Playwright not installed, skipping careers page fetch")

    
    return postings


def fetch_company_jobs(company_name: str, company_domain: str = "") -> list[JobPosting]:
    """
    Fetch job postings for a specific company.
    
    Priority data sources:
    1. Greenhouse.io (public API, works reliably for many tech companies)
    2. Company careers page (Playwright scraping)
    3. LinkedIn (often blocked by anti-bot)
    4. Indeed (often blocked)
    
    Args:
        company_name: Name of the company
        company_domain: Company website domain (optional)
    
    Returns:
        List of JobPosting objects
    """
    job_postings = []
    
    logger.info(f"Searching jobs for: {company_name}")
    
    # 0. Check if this is a Chinese company - use CN sources first
    if _is_chinese_company(company_name):
        logger.info(f"  Detected Chinese company: {company_name}")
        
        # Try known career page via Playwright
        career_url, _ = _get_cn_career_url(company_name)
        cn_careers = _fetch_cn_careers_page(company_name, career_url)
        if cn_careers:
            logger.info(f"  CN careers returned {len(cn_careers)} postings")
            return cn_careers
        
        # Try Lagou API
        lagou_postings = _search_lagou_api(company_name)
        if lagou_postings:
            logger.info(f"  Lagou returned {len(lagou_postings)} postings")
            return lagou_postings
        
        # Try Liepin
        liepin_postings = _search_liepin(company_name)
        if liepin_postings:
            logger.info(f"  Liepin returned {len(liepin_postings)} postings")
            return liepin_postings
        
        # Try Zhilian
        zhaopin_postings = _search_zhaopin(company_name)
        if zhaopin_postings:
            logger.info(f"  Zhilian returned {len(zhaopin_postings)} postings")
            return zhaopin_postings
    
    # 1. Try Greenhouse.io first (most reliable for tech companies)
    gh_postings = _search_greenhouse(company_name)
    if gh_postings:
        logger.info(f"  Greenhouse returned {len(gh_postings)} postings")
        return gh_postings
    
    # 2. Try company careers page via Playwright
    careers_postings = _fetch_company_careers_page(company_name, company_domain)
    if careers_postings:
        logger.info(f"  Careers page returned {len(careers_postings)} postings")
        return careers_postings
    
    # 3. Fallback: Search LinkedIn
    linkedin_info = _fetch_linkedin_company(company_name)
    if linkedin_info["linkedin_url"]:
        logger.info(f"  LinkedIn: {linkedin_info['linkedin_url']}")
    
    # 4. Fallback: Search Indeed
    indeed_info = _fetch_indeed_company(company_name)
    if indeed_info["open_positions"] > 0:
        logger.info(f"  Indeed: {indeed_info['open_positions']} openings")
    
    # If we found job info, create a summary posting
    total_jobs = linkedin_info.get("job_openings_count", 0) + indeed_info.get("open_positions", 0)
    
    if linkedin_info["linkedin_url"] or indeed_info["indeed_jobs_url"] or total_jobs > 0:
        # Create a summary job posting with aggregate info
        from datetime import datetime
        
        sources = []
        if linkedin_info["linkedin_url"]:
            sources.append(f"LinkedIn: {linkedin_info['linkedin_url']}")
        if indeed_info["indeed_jobs_url"]:
            sources.append(f"Indeed: {indeed_info['indeed_jobs_url']}")
        
        job = JobPosting(
            company_name=company_name,
            job_title=f"Hiring: {total_jobs} positions" if total_jobs > 0 else "Open Positions",
            posting_date=datetime.now(),
            source="linkedin" if linkedin_info["linkedin_url"] else "indeed",
            job_count=total_jobs,
        )
        job_postings.append(job)
        logger.info(f"  Created summary posting: {total_jobs} jobs")
    
    return job_postings


def search_jobs(query: str, location: str = "") -> list[dict]:
    """
    Search for jobs matching a query.
    
    Args:
        query: Job search query (role, skill, etc.)
        location: Optional location filter
    
    Returns:
        List of job posting dictionaries
    """
    results = []
    try:
        search_query = f"{query} jobs {location}".strip()
        results = _search_jobs_ddg(search_query)
        logger.info(f"Found {len(results)} job results for: {search_query}")
            
    except Exception as e:
        logger.error(f"Job search failed: {e}")
    
    return results


def fetch_job_postings(company_name: str) -> list[JobPosting]:
    """
    Fetch job postings for a company (Phase 2).
    Wrapper around fetch_company_jobs for main.py compatibility.
    
    Args:
        company_name: Name of the company
    
    Returns:
        List of JobPosting objects
    """
    return fetch_company_jobs(company_name, company_domain="")


def get_company_hiring_info(company_name: str) -> dict:
    """
    Get comprehensive hiring information for a company.
    
    Args:
        company_name: Company name
    
    Returns:
        Dictionary with all hiring info found
    """
    info = {
        "company_name": company_name,
        "is_hiring": False,
        "sources": [],
        "total_positions": 0,
        "linkedin_url": "",
        "indeed_url": "",
        "crunchbase_url": "",
    }
    
    # Search all sources
    linkedin = _fetch_linkedin_company(company_name)
    indeed = _fetch_indeed_company(company_name)
    
    if linkedin.get("linkedin_url"):
        info["sources"].append("LinkedIn")
        info["linkedin_url"] = linkedin["linkedin_url"]
        info["is_hiring"] = True
        
    if indeed.get("indeed_jobs_url") or indeed.get("open_positions", 0) > 0:
        info["sources"].append("Indeed")
        info["indeed_url"] = indeed.get("indeed_jobs_url", "")
        info["total_positions"] += indeed.get("open_positions", 0)
        info["is_hiring"] = True
    
    return info
