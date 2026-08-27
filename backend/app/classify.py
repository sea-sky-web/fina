"""ETF 主题/类型分类 — 纯函数，无 IO 依赖。

从旧系统 app/services/theme_classifier.py::infer_etf_theme 和
app/services/rotation_service.py::infer_etf_type 迁移而来，逻辑不变。
"""
from __future__ import annotations

THEME_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("货币现金", ("货币", "银华日利", "华宝添益")),
    ("宽基指数", ("沪深300", "中证500", "中证1000", "中证2000", "A500", "上证50", "深证100")),
    ("科创创业", ("科创50", "科创100", "科创创业", "创业板", "创业板50", "创业板成长")),
    ("港股中概", ("港股", "恒生", "中概", "香港")),
    ("海外指数", ("纳指", "纳斯达克", "标普", "亚太")),
    ("半导体芯片", ("半导体", "芯片", "集成电路")),
    ("科技AI", ("人工智能", "AI", "机器人", "卫星", "通信", "科技", "信息技术")),
    ("医药医疗", ("创新药", "医疗", "医药")),
    ("金融地产", ("证券", "券商", "银行", "非银", "证券保险")),
    ("资源能源", ("黄金", "黄金股", "有色", "煤炭", "能源", "油气", "化工", "电力")),
    ("消费", ("消费", "酒")),
    ("新能源", ("电池", "储能", "光伏", "电网")),
    ("红利低波", ("红利", "低波")),
]

# 只有这两类会进入 v1 的实时轮动候选池
ANALYZABLE_ETF_TYPES = {"行业", "主题"}


def infer_etf_theme(name: str | None, index_name: str | None = None) -> str:
    text = f"{name or ''}{index_name or ''}".upper()
    for theme, keywords in THEME_RULES:
        if any(keyword.upper() in text for keyword in keywords):
            return theme
    return "其他"


def infer_etf_type(name: str | None, theme: str) -> str:
    text = f"{name or ''}{theme}".upper()
    if theme == "货币现金" or any(keyword in text for keyword in ["货币", "债", "国债", "政金债"]):
        return "货币债券"
    if theme in {"宽基指数", "科创创业"}:
        return "宽基"
    if theme == "海外指数":
        return "主题"
    if theme in {"红利低波"} or any(
        keyword in text for keyword in ["红利", "低波", "价值", "质量"]
    ):
        return "风格"
    if theme in {"科技AI", "新能源", "港股中概"}:
        return "主题"
    if theme in {"半导体芯片", "医药医疗", "金融地产", "资源能源", "消费"}:
        return "行业"
    return "其他"


def is_sector_or_theme(name: str | None, index_name: str | None = None) -> bool:
    theme = infer_etf_theme(name, index_name)
    return infer_etf_type(name, theme) in ANALYZABLE_ETF_TYPES
