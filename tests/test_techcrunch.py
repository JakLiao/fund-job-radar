"""Unit tests for TechCrunch RSS scraper."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.scrapers.techcrunch import (
    _extract_amount,
    _extract_round,
    _extract_company_name,
    _parse_amount,
)


class TestParseAmount:
    """Tests for _parse_amount function."""

    def test_parse_thousands(self):
        assert _parse_amount("$10K") == 10_000
        assert _parse_amount("500k") == 500_000

    def test_parse_millions(self):
        assert _parse_amount("$10M") == 10_000_000
        assert _parse_amount("5.5m") == 5_500_000

    def test_parse_billions(self):
        assert _parse_amount("$2B") == 2_000_000_000
        assert _parse_amount("1.5b") == 1_500_000_000

    def test_parse_with_commas(self):
        assert _parse_amount("$10,000,000") == 10_000_000
        assert _parse_amount("5,000,000") == 5_000_000

    def test_invalid_input(self):
        assert _parse_amount("") is None
        assert _parse_amount("abc") is None
        assert _parse_amount(None) is None


class TestExtractRound:
    """Tests for _extract_round function."""

    def test_series_a(self):
        assert _extract_round("Company raises $10M Series A") == "A"

    def test_series_b(self):
        assert _extract_round("Startup lands $50M Series B funding") == "B"

    def test_series_c_plus(self):
        assert _extract_round("TechCo closes $100M Series C") == "C"

    def test_seed(self):
        assert _extract_round("Startup raises $2M Seed round") == "Seed"
        assert _extract_round("Company gets $1M seed funding") == "Seed"

    def test_pre_seed(self):
        assert _extract_round("Pre-Seed startup raises $500K") == "Seed"
        assert _extract_round("Preseed round of $1M announced") == "Seed"

    def test_angel(self):
        assert _extract_round("Startup raises $500K in angel round") == "Seed"

    def test_excludes_ipo(self):
        assert _extract_round("Company IPOs on Nasdaq") is None

    def test_excludes_merger(self):
        assert _extract_round("Company merger with Competitor") is None


class TestExtractAmount:
    """Tests for _extract_amount function."""

    def test_extract_millions(self):
        assert _extract_amount("raises $10M Series A") == 10_000_000
        assert _extract_amount("secures $50M") == 50_000_000

    def test_extract_thousands(self):
        assert _extract_amount("raises $500K seed") == 500_000

    def test_extract_billions(self):
        assert _extract_amount("raises $2B Series D") == 2_000_000_000

    def test_extract_with_commas(self):
        amount = _extract_amount("raises $10,000,000 Series A")
        assert amount == 10_000_000

    def test_extract_no_dollar_sign(self):
        assert _extract_amount("raises 10M Series A") == 10_000_000

    def test_no_amount_below_threshold(self):
        """Amounts below $10K should be filtered."""
        result = _extract_amount("raises $5K seed")
        assert result is None


class TestExtractCompanyName:
    """Tests for _extract_company_name function."""

    def test_simple_title(self):
        result = _extract_company_name("Acme Corp raises $10M Series A")
        assert "Acme Corp" in result

    def test_removes_funding_info(self):
        result = _extract_company_name("Company raises $10M Series A")
        assert "$10M" not in result
        assert "Series A" not in result

    def test_removes_raises_clause(self):
        result = _extract_company_name("Startup raises $5M Seed round from Sequoia")
        assert "raises" not in result.lower()
        assert "Seed" not in result

    def test_removes_to_clause(self):
        result = _extract_company_name("TechStartup raises $15M Series A to expand AI platform")
        assert "to expand" not in result.lower()


def make_mock_entry(title, link, published_parsed, summary):
    """Create a properly mocked feed entry."""
    entry = MagicMock()
    entry.get = lambda key, default=None: {
        "title": title,
        "link": link,
        "published_parsed": published_parsed,
        "summary": summary,
    }.get(key, default)
    return entry


class TestFetchTechCrunchMocked:
    """Tests for fetch_techcrunch_fundings with mocked RSS."""

    @patch("app.scrapers.techcrunch.feedparser.parse")
    def test_parses_valid_feed(self, mock_parse):
        """Test that valid RSS entries are parsed correctly."""
        mock_feed = MagicMock()
        mock_feed.bozo = False
        
        mock_entry = make_mock_entry(
            title="TechStartup raises $15M Series A to expand AI platform",
            link="https://techcrunch.com/2024/01/15/techstartup-raises-15m/",
            published_parsed=(2024, 1, 15, 10, 0, 0, 0, 0, 0),
            summary="TechStartup has raised $15M in Series A funding.",
        )
        
        mock_feed.entries = [mock_entry]
        mock_parse.return_value = mock_feed
        
        from app.scrapers.techcrunch import fetch_techcrunch_fundings
        events = fetch_techcrunch_fundings(limit=50)
        
        assert len(events) == 1
        assert events[0].company_name == "TechStartup"
        assert events[0].round_type == "A"
        assert events[0].amount_cny == 108_000_000
        assert events[0].source == "tc"

    @patch("app.scrapers.techcrunch.feedparser.parse")
    def test_filters_ipo_news(self, mock_parse):
        """Test that IPO announcements are filtered out."""
        mock_feed = MagicMock()
        mock_feed.bozo = False
        
        mock_entry = make_mock_entry(
            title="BigCo IPOs on NYSE raising $1B",
            link="https://techcrunch.com/2024/01/15/bigco-ipo/",
            published_parsed=(2024, 1, 15, 10, 0, 0, 0, 0, 0),
            summary="BigCo goes public today.",
        )
        
        mock_feed.entries = [mock_entry]
        mock_parse.return_value = mock_feed
        
        from app.scrapers.techcrunch import fetch_techcrunch_fundings
        events = fetch_techcrunch_fundings(limit=50)
        
        # IPO should be filtered (no round type)
        assert len(events) == 0

    @patch("app.scrapers.techcrunch.feedparser.parse")
    def test_handles_feed_error(self, mock_parse):
        """Test graceful handling of feed parsing errors."""
        mock_parse.side_effect = Exception("Network error")
        
        from app.scrapers.techcrunch import fetch_techcrunch_fundings
        events = fetch_techcrunch_fundings()
        
        assert events == []

    @patch("app.scrapers.techcrunch.feedparser.parse")
    def test_multiple_entries(self, mock_parse):
        """Test parsing multiple RSS entries."""
        mock_feed = MagicMock()
        mock_feed.bozo = False
        
        entries = []
        test_cases = [
            ("Startup A raises $5M Seed", 5_000_000, "Seed"),
            ("Company B closes $20M Series B", 20_000_000, "B"),
            ("BigCorp secures $100M Series C", 100_000_000, "C"),
        ]
        for i, (title, amount, round_type) in enumerate(test_cases):
            entry = make_mock_entry(
                title=title,
                link=f"https://techcrunch.com/2024/01/{i+1}/news/",
                published_parsed=(2024, 1, i+1, 10, 0, 0, 0, 0, 0),
                summary=title,
            )
            entries.append(entry)
        
        mock_feed.entries = entries
        mock_parse.return_value = mock_feed
        
        from app.scrapers.techcrunch import fetch_techcrunch_fundings
        events = fetch_techcrunch_fundings(limit=50)
        
        assert len(events) == 3
        assert events[0].amount_cny == 36_000_000
        assert events[1].amount_cny == 144_000_000
        assert events[2].amount_cny == 720_000_000
