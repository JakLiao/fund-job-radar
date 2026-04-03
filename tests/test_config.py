"""Unit tests for config module."""

import pytest
from app.config import Config, get_config


class TestConfig:
    """Tests for Config singleton and properties."""

    def test_singleton(self):
        c1 = Config()
        c2 = Config()
        assert c1 is c2

    def test_signal_thresholds(self):
        c = get_config()
        assert c.signal_high_threshold == 15.0
        assert c.signal_medium_threshold == 8.0

    def test_window_days_defaults(self):
        c = get_config()
        assert c.window_seed_days == 45
        assert c.window_series_a_days == 90
        assert c.window_series_b_days == 120
        assert c.window_series_c_plus_days == 180

    def test_score_threshold(self):
        c = get_config()
        assert c.score_threshold == 5.0

    def test_scheduler_intervals(self):
        c = get_config()
        assert c.techcrunch_interval == 30
        assert c.edgar_interval_hours == 6
        assert c.crunchbase_interval == 60

    def test_edgar_config(self):
        c = get_config()
        assert c.edgar_enabled is True
        assert c.edgar_days_lookback == 60
        assert c.edgar_min_amount == 1_800_000  # CNY: $250k USD × 7.2 ≈ 180万元

    def test_database_path(self):
        c = get_config()
        assert "fund_job_radar.db" in c.database_path

    def test_notification_settings(self):
        c = get_config()
        assert "09:00" in c.push_times
        assert c.quiet_hours_start == "22:00"
        assert c.quiet_hours_end == "08:00"

    def test_get_with_dot_notation(self):
        c = get_config()
        assert c.get("scoring.score_threshold") == 5.0
        assert c.get("nonexistent.key", "default") == "default"

    def test_feishu_webhook(self):
        c = get_config()
        assert "feishu" in c.feishu_webhook.lower()
