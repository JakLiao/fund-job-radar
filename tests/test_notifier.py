"""Unit tests for notifier module."""

import pytest
from app.notifier import _format_amount


class TestFormatAmount:
    """Tests for _format_amount helper (amount now in CNY yuan)."""

    def test_yi_yuan(self):
        # 1亿元 = 100,000,000 CNY
        assert _format_amount(100_000_000) == "¥1.0亿元"

    def test_qianwan_yuan(self):
        # 5千万元 = 50,000,000 CNY
        assert _format_amount(50_000_000) == "¥5.0千万元"

    def test_baiwan_yuan(self):
        # 1.5百万元 = 1,500,000 CNY
        assert _format_amount(1_500_000) == "¥1.5百万元"

    def test_wan_yuan(self):
        # 500万元 = 5,000,000 CNY
        assert _format_amount(5_000_000) == "¥5.0百万元"

    def test_small_wan(self):
        # 25万元 = 250,000 CNY
        assert _format_amount(250_000) == "¥25.0万元"

    def test_very_small(self):
        # 5000元 (smallest)
        assert _format_amount(5_000) == "¥5,000元"

    def test_zero_no_source(self):
        assert _format_amount(0) == "未知"

    def test_zero_edgar_source(self):
        # EDGAR often doesn't disclose amount
        assert _format_amount(0, "edgar") == "金额未披露"

    def test_zero_tc_source(self):
        assert _format_amount(0, "tc") == "未知"

    def test_exact_boundary_yi(self):
        # Exactly 100 million
        assert _format_amount(100_000_000) == "¥1.0亿元"

    def test_exact_boundary_qianwan(self):
        # Exactly 10 million
        assert _format_amount(10_000_000) == "¥1.0千万元"

    def test_exact_boundary_baiwan(self):
        # Exactly 1 million
        assert _format_amount(1_000_000) == "¥1.0百万元"

    def test_exact_boundary_wan(self):
        # Exactly 10,000
        assert _format_amount(10_000) == "¥1.0万元"
