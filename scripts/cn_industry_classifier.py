"""Chinese company industry classifier.

Provides industry classification for Chinese startup company names.
Used to fill industry_group field for CN funding events.

Classification priority:
1. Known companies knowledge base (exact match)
2. Keyword pattern matching
3. Unknown (returns None)
"""

from typing import Optional

# ==============================================================================
# Known companies knowledge base
# Maps company name (full or partial) → industry_group
# ==============================================================================

KNOWN_COMPANIES = {
    # AI + Biotech
    "华深智药": "Artificial Intelligence",
    
    # Robotics
    "法奥机器人": "Robotics / Industrial",
    "艾利特机器人": "Robotics / Industrial",
    "傲意科技": "Robotics / Industrial",
    "中微精仪": "Robotics / Industrial",
    "青心意创": "Robotics / Industrial",
    
    # Healthcare
    "图湃医疗": "Biotechnology / Healthcare",
    "犀燃医疗": "Biotechnology / Healthcare",
    
    # New Energy
    "富德金煜": "New Energy / Materials",
    "合壹新能": "New Energy / Materials",
    
    # AI
    "光象科技": "Artificial Intelligence",
    "星灿智能": "Artificial Intelligence",
    "鼎犀智创": "Artificial Intelligence",
    
    # Biotech
    "迈博智星": "Biotechnology / Healthcare",
    "合成纪元": "Biotechnology / Healthcare",
    
    # Cybersecurity
    "无界方舟": "Cybersecurity",
    
    # Consumer
    "珀乐互动": "Consumer / Retail",
    "质子心宠": "Consumer / Retail",
    "爱睿思": "Consumer / Retail",
    
    # AgriTech
    "Fungifuture": "Agriculture / Food",
}

# ==============================================================================
# Keyword-based classification patterns
# Order matters: first match wins
# ==============================================================================

INDUSTRY_PATTERNS = [
    # Healthcare / Biotech (check before general "药" which might overlap)
    ("Biotechnology / Healthcare", ["医疗", "医药", "生物", "制药", "基因", "蛋白", "新药", "健康", "心宠", "药"]),
    
    # Robotics / Industrial
    ("Robotics / Industrial", ["机器人", "智造", "自动化", "智控", "机甲", "精密", "智仪"]),
    
    # Artificial Intelligence
    ("Artificial Intelligence", ["人工智能", "智药", "智创", "智能", "AI", "智算", "大模型", "星智能", "心创"]),
    
    # Semiconductors / Chips
    ("Semiconductors / Chips", ["芯片", "半导体", "集成电路", "晶圆"]),
    
    # New Energy / Materials
    ("New Energy / Materials", ["能源", "储能", "光伏", "锂电", "电池", "新能", "材料", "稀土", "煜"]),
    
    # Enterprise Software / SaaS
    ("Enterprise Software / SaaS", ["软件", "云", "数据", "SaaS", "科技", "象科技"]),
    
    # Autonomous Driving / Mobility
    ("Autonomous Driving / Mobility", ["出行", "物流", "自动驾驶", "汽车", "车"]),
    
    # Agriculture / Food
    ("Agriculture / Food", ["农业", "农", "种", "畜牧", "食品"]),
    
    # Consumer / Retail
    ("Consumer / Retail", ["消费", "零售", "电商", "互动"]),
    
    # Cybersecurity
    ("Cybersecurity", ["安全", "网络安全", "方舟"]),
]


def classify_industry(company_name: str) -> Optional[str]:
    """
    Classify a Chinese company into an industry group.
    
    Args:
        company_name: The company name (Chinese or English)
    
    Returns:
        Industry group string, or None if unknown
    """
    if not company_name:
        return None
    
    # 1. Try known companies knowledge base (exact substring match)
    for known_name, industry in KNOWN_COMPANIES.items():
        if known_name in company_name:
            return industry
    
    # 2. Try keyword pattern matching
    for industry, keywords in INDUSTRY_PATTERNS:
        for kw in keywords:
            if kw in company_name:
                return industry
    
    # 3. Unknown
    return None


if __name__ == "__main__":
    # Test with the known companies
    test_companies = [
        "无界方舟", "富德金煜", "合成纪元", "犀燃医疗", "合壹新能",
        "中微精仪", "傲意科技", "图湃医疗", "鼎犀智创", "艾利特机器人",
        "光象科技", "珀乐互动", "法奥机器人", "青心意创", "星灿智能",
        "华深智药", "质子心宠", "Fungifuture", "迈博智星", "爱睿思",
    ]
    
    print("Industry classification test:")
    print("-" * 60)
    for name in test_companies:
        result = classify_industry(name)
        print(f"  {name:20s} → {result}")
