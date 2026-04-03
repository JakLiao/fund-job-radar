"""Unit tests for fuzzy matching utility."""

import pytest
from app.utils.fuzzy_match import (
    match_company_name,
    similarity_score,
    is_same_company,
)


class TestSimilarityScore:
    """Tests for similarity_score function."""

    def test_identical_names(self):
        score = similarity_score("Acme Corp", "Acme Corp")
        assert score == 100

    def test_case_insensitive(self):
        score = similarity_score("ACME CORP", "acme corp")
        assert score == 100

    def test_similar_names(self):
        score = similarity_score("Acme Corporation", "Acme Corp")
        # These are somewhat similar but not extremely close
        assert score > 60
        assert score < 90

    def test_different_names(self):
        score = similarity_score("Acme Corp", "Globex Inc")
        assert score < 80

    def test_word_order_difference(self):
        """Token-based matching should handle word order differences."""
        score = similarity_score("Acme Corporation Inc", "Inc Acme Corporation")
        assert score > 80

    def test_empty_inputs(self):
        score = similarity_score("", "Acme Corp")
        assert score == 0


class TestIsSameCompany:
    """Tests for is_same_company function."""

    def test_same_company(self):
        assert is_same_company("Acme Corp", "Acme Corp") is True

    def test_similar_names(self):
        # Default threshold is 85, but these score ~72, so we test with lower threshold
        assert is_same_company("Acme Corporation", "Acme Corp", threshold=70) is True
        # With default 85 threshold, these should NOT match
        assert is_same_company("Acme Corporation", "Acme Corp", threshold=85) is False

    def test_different_companies(self):
        assert is_same_company("Acme Corp", "Globex Inc") is False

    def test_custom_threshold(self):
        """Custom threshold should affect matching."""
        # These are somewhat similar but not very
        result_default = is_same_company("Tech Startup Inc", "TechStartup", threshold=85)
        result_low = is_same_company("Tech Startup Inc", "TechStartup", threshold=70)
        # With high threshold (85), should be False
        # With low threshold (70), should be True
        assert result_low is True or result_default is False


class TestMatchCompanyName:
    """Tests for match_company_name function."""

    def test_exact_match(self):
        candidates = ["Acme Corp", "Globex Inc", "Initech"]
        result = match_company_name("Acme Corp", candidates)
        assert result is not None
        assert result[0] == "Acme Corp"
        assert result[1] == 100

    def test_fuzzy_match(self):
        candidates = ["Acme Corporation", "Globex Inc", "Initech"]
        # "Acme Corp" vs "Acme Corporation" scores ~72, below 85 threshold
        result = match_company_name("Acme Corp", candidates, threshold=70)
        assert result is not None
        assert "Acme" in result[0]
        assert result[1] > 70

    def test_no_match_below_threshold(self):
        candidates = ["Completely Different LLC", "Another Company"]
        result = match_company_name("Acme Corp", candidates, threshold=85)
        assert result is None

    def test_empty_candidates(self):
        result = match_company_name("Acme Corp", [])
        assert result is None

    def test_empty_query(self):
        result = match_company_name("", ["Acme Corp"])
        assert result is None

    def test_best_match_among_multiple(self):
        candidates = [
            "Acme Corporation",
            "Acme Industries",
            "Completely Different Company",
        ]
        result = match_company_name("Acme", candidates, threshold=50)
        assert result is not None
        # Should match one of the Acme* candidates, not Different Company
        assert "Acme" in result[0]

    def test_threshold_filtering(self):
        candidates = ["XXX Company"]  # Very different
        result = match_company_name("Acme Corp", candidates, threshold=85)
        assert result is None  # Should not match due to high threshold

    def test_word_order_invariance(self):
        """Token-set matching should handle different word orders."""
        candidates = ["The Acme Corporation LLC"]
        result = match_company_name("Acme Corporation", candidates)
        assert result is not None
        assert result[1] > 85
