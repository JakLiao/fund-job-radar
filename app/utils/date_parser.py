"""Shared date parsing utilities — eliminates duplicate date parsing across scrapers."""

from datetime import datetime


def parse_date(date_str: str) -> datetime:
    """
    Parse a date string into a datetime object.
    Tries multiple common formats, returns datetime.now() as fallback.
    """
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d-%b-%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return datetime.now()
