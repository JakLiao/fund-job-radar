"""Data models for Fund Job Radar."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


@dataclass
class FundingEvent:
    """融资事件数据模型."""
    company_name: str
    announcement_date: datetime
    round_type: str  # Seed/A/B/C/D
    amount_cny: float  # 金额（人民币元）
    source: str  # tc/edgar/crunchbase
    company_domain: str = ""
    investors: str = ""
    source_url: str = ""
    industry_group: str = ""  # 行业分类 (EDGAR)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class JobPosting:
    """招聘信息数据模型."""
    company_name: str
    job_title: str
    posting_date: datetime
    source: str  # linkedin/indeed/官网
    job_count: int = 1
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Opportunity:
    """商机数据模型."""
    company_name: str
    funding_event_id: str
    signal_strength: str  # HIGH/MEDIUM/LOW
    window_days_remaining: int
    recommended_action: str
    status: str = "new"  # new/sent/archived
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.now)
