"""Unit tests for shared date_parser utility."""

import pytest
from datetime import datetime
from app.utils.date_parser import parse_date


class TestParseDate:
    """Tests for parse_date function."""

    def test_iso_format(self):
        result = parse_date("2026-03-15")
        assert result == datetime(2026, 3, 15)

    def test_slash_format(self):
        result = parse_date("2026/03/15")
        assert result == datetime(2026, 3, 15)

    def test_us_format(self):
        result = parse_date("03/15/2026")
        assert result == datetime(2026, 3, 15)

    def test_dash_bug_year(self):
        result = parse_date("15-Mar-2026")
        assert result == datetime(2026, 3, 15)

    def test_fallback_for_invalid(self):
        # Invalid format should return datetime.now() (within a few seconds)
        before = datetime.now()
        result = parse_date("not-a-date-at-all")
        after = datetime.now()
        # Result should be close to now
        delta = result - before
        assert delta.total_seconds() < 2
        delta2 = after - result
        assert delta2.total_seconds() < 2
