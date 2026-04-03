"""Unit tests for Chinese funding scraper — no network calls required."""

import pytest
from app.scrapers.cn_funding import (
    _parse_cn_amount,
    _parse_round_type,
)
from scripts.cn_industry_classifier import classify_industry


class TestParseCnAmount:
    """Tests for _parse_cn_amount function."""

    def test_yi_renminbi(self):
        # "1亿人民币" = 100,000,000 CNY (1×10⁸元)
        amount = _parse_cn_amount("1亿人民币")
        assert amount == 100_000_000.0

    def test_yi_meiyuan(self):
        # "1亿美元" = 1e8 USD × 7.2 = 720,000,000 CNY
        amount = _parse_cn_amount("1亿美元")
        assert amount == 720_000_000.0

    def test_qianwan_renminbi(self):
        # "1千万人民币" = 10,000,000 CNY
        amount = _parse_cn_amount("1千万人民币")
        assert amount == 10_000_000.0

    def test_baiwan_renminbi(self):
        # "1百万人民币" = 1,000,000 CNY
        amount = _parse_cn_amount("1百万人民币")
        assert amount == 1_000_000.0

    def test_wan_meiyuan(self):
        # "500万USD" = 500×10,000 USD × 7.2 = 36,000,000 CNY
        amount = _parse_cn_amount("500万USD")
        assert amount == 36_000_000.0

    def test_dollar_million(self):
        # "$5 million" uses Chinese 百万, not English "million"
        amount = _parse_cn_amount("$5 million")
        assert amount is None  # function only handles Chinese units

    def test_dollar_millions(self):
        # "$$5 millions" - double $ not normalized, returns None
        amount = _parse_cn_amount("$$5 millions")
        assert amount is None

    def test_dollar_billion(self):
        # "$1.5B" = 1.5×10⁹ USD × 7.2 = 10,800,000,000 CNY
        amount = _parse_cn_amount("$1.5B")
        assert amount == 10_800_000_000.0

    def test_vague_shue_yi(self):
        # "数亿" ≈ 5e7 CNY
        amount = _parse_cn_amount("该公司获得数亿人民币投资")
        assert amount is not None

    def test_vague_chi_xun_qianwan(self):
        # "超千万" ≈ 1e7 CNY
        amount = _parse_cn_amount("获得超千万人民币融资")
        assert amount is not None

    def test_empty_string(self):
        assert _parse_cn_amount("") is None

    def test_no_amount_pattern(self):
        # No recognizable pattern → None
        assert _parse_cn_amount("这是一段普通文本没有金额信息") is None


class TestParseRoundType:
    """Tests for _parse_round_type function."""

    def test_seed_not_matched_as_amount(self):
        # "天使轮" contains no amount keyword → should return None
        assert _parse_cn_amount("天使轮") is None

    def test_pre_a(self):
        assert _parse_round_type("Pre-A轮融资") == "Pre-A"
        assert _parse_round_type("pre-a融资") == "Pre-A"

    def test_series_a(self):
        assert _parse_round_type("A轮融资") == "A"
        assert _parse_round_type("A+轮") == "A"   # A+ normalizes to A
        assert _parse_round_type("A轮") == "A"

    def test_series_b(self):
        assert _parse_round_type("B轮融资") == "B"
        assert _parse_round_type("B+轮") == "B"   # B+ normalizes to B

    def test_series_c_plus(self):
        assert _parse_round_type("C轮融资") == "C"
        assert _parse_round_type("D轮") == "D"

    def test_angel(self):
        assert _parse_round_type("天使轮") == "Angel"
        assert _parse_round_type("天使投资") == "Angel"

    def test_pre_ipo(self):
        assert _parse_round_type("Pre-IPO融资") == "Pre-IPO"

    def test_strategy_investment(self):
        assert _parse_round_type("战略投资") == "战略投资"

    def test_excludes_ipo(self):
        # 上市 (IPO) → excluded
        assert _parse_round_type("公司上市IPO") is None

    def test_excludes_ma(self):
        # 并购/收购 → excluded
        assert _parse_round_type("被并购") is None
        assert _parse_round_type("收购某公司") is None

    def test_excludes_share_repurchase(self):
        # 减持/增发/回购/退市 → excluded
        assert _parse_round_type("股份回购") is None
        assert _parse_round_type("定向增发") is None


class TestClassifyIndustry:
    """Tests for classify_industry function."""

    def test_known_ai_companies(self):
        assert classify_industry("华深智药") == "Artificial Intelligence"
        assert classify_industry("鼎犀智创") == "Artificial Intelligence"
        assert classify_industry("光象科技") == "Artificial Intelligence"
        assert classify_industry("星灿智能") == "Artificial Intelligence"

    def test_known_healthcare_companies(self):
        assert classify_industry("图湃医疗") == "Biotechnology / Healthcare"
        assert classify_industry("犀燃医疗") == "Biotechnology / Healthcare"
        assert classify_industry("合成纪元") == "Biotechnology / Healthcare"
        assert classify_industry("迈博智星") == "Biotechnology / Healthcare"

    def test_known_robotics_companies(self):
        assert classify_industry("法奥机器人") == "Robotics / Industrial"
        assert classify_industry("艾利特机器人") == "Robotics / Industrial"
        assert classify_industry("傲意科技") == "Robotics / Industrial"
        assert classify_industry("中微精仪") == "Robotics / Industrial"

    def test_known_energy_companies(self):
        assert classify_industry("富德金煜") == "New Energy / Materials"
        assert classify_industry("合壹新能") == "New Energy / Materials"

    def test_known_cybersecurity(self):
        assert classify_industry("无界方舟") == "Cybersecurity"

    def test_unknown_returns_none(self):
        assert classify_industry("未知公司XYZ123") is None
        assert classify_industry("Random Corp") is None
