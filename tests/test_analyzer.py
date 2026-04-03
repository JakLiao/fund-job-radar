"""Unit tests for analyzer module."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from app.analyzer import (
    calculate_window,
    calculate_score,
    _get_signal_strength,
    _get_recommended_action,
)


class TestCalculateWindow:
    """Tests for calculate_window function."""

    def test_seed_window(self):
        with patch("app.analyzer.get_config") as mock_config:
            mock_config.return_value.window_seed_days = 14
            assert calculate_window("Seed") == 14

    def test_series_a_window(self):
        with patch("app.analyzer.get_config") as mock_config:
            mock_config.return_value.window_series_a_days = 45
            assert calculate_window("A") == 45

    def test_series_b_window(self):
        with patch("app.analyzer.get_config") as mock_config:
            mock_config.return_value.window_series_b_days = 60
            assert calculate_window("B") == 60

    def test_series_c_plus_window(self):
        with patch("app.analyzer.get_config") as mock_config:
            mock_config.return_value.window_series_c_plus_days = 90
            assert calculate_window("C") == 90
            assert calculate_window("D") == 90
            assert calculate_window("E") == 90
            assert calculate_window("F") == 90

    def test_case_insensitive(self):
        with patch("app.analyzer.get_config") as mock_config:
            mock_config.return_value.window_seed_days = 14
            assert calculate_window("seed") == 14
            assert calculate_window("SEED") == 14


class TestCalculateScore:
    """Tests for calculate_score function."""

    def test_seed_small_round(self):
        """Score for small seed round with full window (amount now in CNY)."""
        score = calculate_score("Seed", 2_000_000, 14)
        # 1.0 * log10(2M/7.2 + 1) * 14 / 10 ≈ 7.62
        # (2M CNY ≈ $277k USD)
        assert score > 7.5
        assert score < 10

    def test_series_a_medium_round(self):
        """Score for Series A with medium window."""
        score = calculate_score("A", 10_000_000, 30)
        # 2.0 * log10(10000001) * 30 / 10
        # log10(10000001) ≈ 7.0
        # 2.0 * 7.0 * 30 / 10 = 42
        assert score > 30
        assert score < 50

    def test_series_b_large_round(self):
        """Score for large Series B with full window."""
        score = calculate_score("B", 50_000_000, 60)
        # 3.0 * log10(50000001) * 60 / 10
        # log10(50000001) ≈ 7.7
        # 3.0 * 7.7 * 60 / 10 ≈ 138.6
        assert score > 100

    def test_zero_window(self):
        """Score should be 0 if window is 0."""
        score = calculate_score("A", 10_000_000, 0)
        assert score == 0

    def test_unknown_round_type(self):
        """Unknown round type should use default weight (1.0)."""
        score = calculate_score("Unknown", 10_000_000, 30)
        # Should use weight 1.0, not crash
        assert score > 0

    def test_boundary_conditions(self):
        """Test boundary conditions for score calculation."""
        # Minimal amount
        score_min = calculate_score("Seed", 0, 14)
        # log10(1) = 0, so score should be ~0
        assert score_min < 1

        # Very large amount
        score_large = calculate_score("C", 1_000_000_000, 90)
        assert score_large > 200


class TestSignalStrength:
    """Tests for _get_signal_strength function."""

    def test_high_strength(self):
        with patch("app.analyzer.get_config") as mock_config:
            mock_config.return_value.signal_high_threshold = 15.0
            mock_config.return_value.signal_medium_threshold = 8.0
            assert _get_signal_strength(20) == "HIGH"
            assert _get_signal_strength(15) == "HIGH"

    def test_medium_strength(self):
        with patch("app.analyzer.get_config") as mock_config:
            mock_config.return_value.signal_high_threshold = 15.0
            mock_config.return_value.signal_medium_threshold = 8.0
            assert _get_signal_strength(14) == "MEDIUM"
            assert _get_signal_strength(8) == "MEDIUM"

    def test_low_strength(self):
        with patch("app.analyzer.get_config") as mock_config:
            mock_config.return_value.signal_high_threshold = 15.0
            mock_config.return_value.signal_medium_threshold = 8.0
            assert _get_signal_strength(7) == "LOW"
            assert _get_signal_strength(0) == "LOW"
            assert _get_signal_strength(1) == "LOW"


class TestRecommendedAction:
    """Tests for _get_recommended_action function."""

    def test_urgent_window(self):
        """Window <= 7 days should indicate urgency."""
        action = _get_recommended_action("Seed", 5)
        assert "窗口即将关闭" in action

    def test_moderate_window(self):
        """Window 8-30 days should indicate moderate urgency."""
        action = _get_recommended_action("A", 20)
        assert "尽快行动" in action

    def test_early_window(self):
        """Window > 30 days should indicate time to prepare."""
        action = _get_recommended_action("B", 45)
        assert "还有时间准备" in action

    def test_seed_recommendation(self):
        """Seed round should recommend engineering/product roles."""
        action = _get_recommended_action("Seed", 14)
        assert "工程师" in action or "产品" in action

    def test_series_a_recommendation(self):
        """Series A should recommend sales/operations roles."""
        action = _get_recommended_action("A", 30)
        assert "销售" in action or "运营" in action

    def test_series_b_recommendation(self):
        """Series B should recommend management roles."""
        action = _get_recommended_action("B", 45)
        assert "管理" in action or "中层" in action

    def test_series_c_plus_recommendation(self):
        """Series C+ should recommend business/strategy roles."""
        action = _get_recommended_action("C", 60)
        assert "商务" in action or "战略" in action
