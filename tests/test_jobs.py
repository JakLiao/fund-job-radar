"""Unit tests for jobs scraper module — no network calls required."""

import pytest
from unittest.mock import patch, MagicMock

from app.scrapers.jobs import (
    _clean_company_name,
    _is_chinese_company,
    _get_cn_career_url,
)


class TestCleanCompanyName:
    """Tests for _clean_company_name function."""

    def test_removes_llc(self):
        assert _clean_company_name("Acme LLC") == "Acme"
        assert _clean_company_name("Acme, LLC") == "Acme"

    def test_removes_lp(self):
        assert _clean_company_name("Venture LP") == "Venture"
        assert _clean_company_name("Fund L.P.") == "Fund"

    def test_removes_inc(self):
        assert _clean_company_name("OpenAI Inc") == "OpenAI"
        assert _clean_company_name("Anthropic, Inc.") == "Anthropic"

    def test_removes_corp(self):
        assert _clean_company_name("Google Corp") == "Google"
        assert _clean_company_name("Data Corp.") == "Data"

    def test_preserves_normal_name(self):
        assert _clean_company_name("Stripe") == "Stripe"
        assert _clean_company_name("Notion") == "Notion"

    def test_case_preserved(self):
        assert _clean_company_name("OPENAI LLC") == "OPENAI"


class TestIsChineseCompany:
    """Tests for _is_chinese_company function."""

    def test_known_chinese_companies(self):
        assert _is_chinese_company("字节跳动") is True
        assert _is_chinese_company("阿里巴巴") is True
        assert _is_chinese_company("腾讯科技") is True
        assert _is_chinese_company("小米集团") is True
        assert _is_chinese_company("大疆创新") is True
        assert _is_chinese_company("商汤科技") is True
        assert _is_chinese_company("理想汽车") is True
        assert _is_chinese_company("蔚来汽车") is True

    def test_known_chinese_pinyin(self):
        assert _is_chinese_company("bytedance") is True
        assert _is_chinese_company("alibaba") is True
        assert _is_chinese_company("tencent") is True
        assert _is_chinese_company("dji") is True
        assert _is_chinese_company("sensetime") is True
        assert _is_chinese_company("idealauto") is True

    def test_us_tech_companies(self):
        assert _is_chinese_company("OpenAI") is False
        assert _is_chinese_company("Anthropic") is False
        assert _is_chinese_company("Stripe") is False
        assert _is_chinese_company("Figma") is False
        assert _is_chinese_company("Datadog") is False

    def test_mixed_names(self):
        # Substring match on known patterns
        assert _is_chinese_company("字节跳动有限公司") is True
        assert _is_chinese_company("阿里巴巴集团") is True


class TestGetCnCareerUrl:
    """Tests for _get_cn_career_url function."""

    def test_direct_map_match(self):
        url, src = _get_cn_career_url("字节跳动")
        assert "bytedance" in url.lower() or "liepin" in src

        url2, src2 = _get_cn_career_url("小米")
        assert src2 == "liepin"

    def test_unknown_company_fallback(self):
        url, src = _get_cn_career_url("未知的科技有限公司")
        assert "careers" in url
        assert src == "careers"

    def test_partial_name_match(self):
        # Should find 字节 in "字节跳动科技"
        url, src = _get_cn_career_url("字节跳动科技")
        assert "bytedance" in url.lower() or src == "liepin"
