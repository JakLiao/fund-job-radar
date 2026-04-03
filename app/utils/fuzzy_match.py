"""Fuzzy matching for company names using rapidfuzz."""

import logging
from typing import Optional

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

# Default similarity threshold (0-100)
DEFAULT_THRESHOLD = 85


def match_company_name(
    query: str,
    candidates: list[str],
    threshold: int = DEFAULT_THRESHOLD,
) -> Optional[tuple[str, int]]:
    """
    Find the best matching company name from a list of candidates.
    
    Args:
        query: The company name to match
        candidates: List of candidate company names
        threshold: Minimum similarity score (0-100) to return a match
    
    Returns:
        A tuple of (matched_name, score) if match found above threshold, else None
    """
    if not query or not candidates:
        return None

    # Use multiple fuzzy matchers and take the best result
    result = process.extractOne(
        query,
        candidates,
        scorer=fuzz.token_set_ratio,
    )

    if result and result[1] >= threshold:
        return (result[0], result[1])

    # Try with token_sort_ratio as fallback
    result = process.extractOne(
        query,
        candidates,
        scorer=fuzz.token_sort_ratio,
    )

    if result and result[1] >= threshold:
        return (result[0], result[1])

    return None


def similarity_score(name1: str, name2: str) -> int:
    """
    Calculate similarity score between two company names.
    
    Args:
        name1: First company name
        name2: Second company name
    
    Returns:
        Similarity score from 0 to 100
    """
    # Use token_set_ratio for robustness (handles word order differences)
    return fuzz.token_set_ratio(name1.lower(), name2.lower())


def is_same_company(name1: str, name2: str, threshold: int = DEFAULT_THRESHOLD) -> bool:
    """
    Check if two company names likely refer to the same company.
    
    Args:
        name1: First company name
        name2: Second company name
        threshold: Minimum similarity score to consider same
    
    Returns:
        True if names are likely the same company
    """
    return similarity_score(name1, name2) >= threshold
