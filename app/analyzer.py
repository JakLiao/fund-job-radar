"""Core analysis engine for Fund Job Radar."""

import logging
import math
from datetime import datetime

from .config import get_config
from .database import (
    get_all_funding_events,
    get_funding_by_id,
    insert_opportunity,
)
from .models import FundingEvent, Opportunity

logger = logging.getLogger(__name__)

# Round type weights (for scoring formula)
ROUND_WEIGHTS = {
    "Seed": 1.0,
    "A": 2.0,
    "B": 3.0,
    "C": 4.0,
    "D": 4.5,
    "E": 5.0,
    "F": 5.0,
}


def calculate_window(round_type: str) -> int:
    """
    Calculate the opportunity window in days based on funding round type.
    
    Args:
        round_type: Funding round (Seed, A, B, C+)
    
    Returns:
        Number of days in the opportunity window
    """
    config = get_config()
    
    round_upper = round_type.upper()
    
    if round_upper == "SEED":
        return config.window_seed_days
    elif round_upper == "A":
        return config.window_series_a_days
    elif round_upper == "B":
        return config.window_series_b_days
    else:
        # C, D, E, F+ all use C+ window
        return config.window_series_c_plus_days


def calculate_score(round_type: str, amount_cny: float, window_days_remaining: int) -> float:
    """
    Calculate opportunity score based on SPEC.md formula.

    Score = round_type_weight x log10(amount_cny + 1) x window_days_remaining / 10

    Note: amount_cny stores CNY (yuan). We divide by 7.2 to convert to
    USD-equivalent before applying log, so the score is consistent.
    """
    weight = ROUND_WEIGHTS.get(round_type, 1.0)
    log_amount = math.log10(amount_cny / 7.2 + 1)  # Normalize CNY → USD-equivalent log
    score = weight * log_amount * window_days_remaining / 10
    return round(score, 2)


def _get_signal_strength(score: float) -> str:
    """Determine signal strength based on score."""
    config = get_config()
    if score >= config.signal_high_threshold:
        return "HIGH"
    elif score >= config.signal_medium_threshold:
        return "MEDIUM"
    else:
        return "LOW"


def _get_recommended_action(round_type: str, window_days: int) -> str:
    """Generate a recommended action based on funding round and window."""
    round_upper = round_type.upper()
    
    if window_days <= 7:
        time_pressure = "窗口即将关闭！"
    elif window_days <= 30:
        time_pressure = "建议尽快行动"
    else:
        time_pressure = "还有时间准备"
    
    if round_upper == "SEED":
        return f"{time_pressure}，早期团队扩张中，关注工程师和产品岗位"
    elif round_upper == "A":
        return f"{time_pressure}，B端/C端团队快速扩张，关注销售和运营岗位"
    elif round_upper == "B":
        return f"{time_pressure}，中大型团队招聘，关注中高层管理岗"
    else:
        return f"{time_pressure}，规模化阶段，关注商务和战略岗位"


def generate_opportunities(funding_event: FundingEvent) -> Opportunity:
    """
    Generate an Opportunity from a FundingEvent.
    
    Args:
        funding_event: The funding event to analyze
    
    Returns:
        A new Opportunity object
    """
    window_days = calculate_window(funding_event.round_type)
    
    # Calculate how many days have passed since announcement
    days_since = (datetime.now() - funding_event.announcement_date).days
    window_remaining = max(0, window_days - days_since)
    
    score = calculate_score(
        funding_event.round_type,
        funding_event.amount_cny,
        window_remaining,
    )
    
    signal_strength = _get_signal_strength(score)
    recommended_action = _get_recommended_action(funding_event.round_type, window_remaining)
    
    opportunity = Opportunity(
        company_name=funding_event.company_name,
        funding_event_id=funding_event.id,
        signal_strength=signal_strength,
        window_days_remaining=window_remaining,
        recommended_action=recommended_action,
        status="new",
    )
    
    logger.info(
        f"Generated opportunity: {funding_event.company_name} "
        f"(score={score}, window={window_remaining}d, strength={signal_strength})"
    )
    
    return opportunity


def process_new_fundings() -> list[Opportunity]:
    """
    Process all funding events and generate opportunities for new ones.
    
    Returns:
        List of newly created Opportunity objects
    """
    fundings = get_all_funding_events()
    new_opportunities = []
    
    for funding in fundings:
        # Calculate window to check if still within window
        window_days = calculate_window(funding.round_type)
        days_since = (datetime.now() - funding.announcement_date).days
        
        if days_since > window_days:
            logger.debug(f"Skipping {funding.company_name}: window expired ({days_since}d > {window_days}d)")
            continue
        
        # Generate opportunity
        opp = generate_opportunities(funding)
        
        # Try to insert (returns False if already exists)
        if insert_opportunity(opp):
            new_opportunities.append(opp)
            logger.info(f"New opportunity created: {opp.company_name}")
        else:
            logger.debug(f"Opportunity already exists: {funding.company_name}")
    
    return new_opportunities


def get_opportunity_summary(opportunities: list[Opportunity]) -> str:
    """
    Generate a formatted summary of opportunities for notification.
    
    Args:
        opportunities: List of Opportunity objects
    
    Returns:
        Formatted summary string
    """
    if not opportunities:
        return "今日暂无新的融资机会"

    lines = [f"📊 融资-招聘信号日报 ({datetime.now().strftime('%Y-%m-%d')})\n"]
    lines.append(f"共发现 {len(opportunities)} 个新机会：\n")

    for opp in opportunities[:10]:  # Cap at 10 for notification length
        funding = get_funding_by_id(opp.funding_event_id)
        if funding:
            amount_str = f"${funding.amount_cny/1e6:.1f}M" if funding.amount_cny >= 1e6 else f"${funding.amount_cny/1e3:.1f}K"
            round_str = funding.round_type
        else:
            amount_str = "N/A"
            round_str = "N/A"

        lines.append(
            f"🏢 {opp.company_name}\n"
            f"   轮次：{round_str} | 金额：{amount_str}\n"
            f"   窗口剩余：约{opp.window_days_remaining}天\n"
            f"   推荐：{opp.recommended_action}\n"
            f"   信号强度：{opp.signal_strength}\n"
        )

    return "\n".join(lines)
