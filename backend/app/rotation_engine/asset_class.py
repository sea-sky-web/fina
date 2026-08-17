"""ETF 资产大类分类器."""

from __future__ import annotations

from enum import StrEnum


class AssetClass(StrEnum):
    EQUITY_SECTOR = "equity_sector"
    EQUITY_BROAD = "equity_broad"
    BOND = "bond"
    COMMODITY = "commodity"
    CROSS_BORDER = "cross_border"
    EXCLUDED = "excluded"


CLASS_BENCHMARK: dict[AssetClass, str] = {
    AssetClass.EQUITY_SECTOR: "510300.SH",
    AssetClass.EQUITY_BROAD: "510300.SH",
    AssetClass.BOND: "511010.SH",
    AssetClass.COMMODITY: "518880.SH",
    AssetClass.CROSS_BORDER: "513050.SH",
}

_EXPLICIT: dict[str, AssetClass] = {
    "511010.SH": AssetClass.BOND,
    "511260.SH": AssetClass.BOND,
    "511220.SH": AssetClass.BOND,
    "518880.SH": AssetClass.COMMODITY,
    "159985.SZ": AssetClass.COMMODITY,
    "159980.SZ": AssetClass.COMMODITY,
    "513100.SH": AssetClass.CROSS_BORDER,
    "513500.SH": AssetClass.CROSS_BORDER,
    "513180.SH": AssetClass.CROSS_BORDER,
    "513050.SH": AssetClass.CROSS_BORDER,
    "159941.SZ": AssetClass.CROSS_BORDER,
    "510500.SH": AssetClass.EQUITY_BROAD,
    "159915.SZ": AssetClass.EQUITY_BROAD,
    "510880.SH": AssetClass.EQUITY_BROAD,
    "510300.SH": AssetClass.EQUITY_BROAD,
}

_EXCLUDED_KW = ("货币", "添益", "现金", "保证金")
_COMMODITY_KW = ("黄金", "上海金", "豆粕", "有色金属", "白银", "原油", "能源化工", "铜")
_BOND_KW = (
    "国债", "国开", "政金债", "地方债", "城投债", "企债",
    "公司债", "信用债", "可转债", "债券", "短融", "利率",
)
_CROSS_BORDER_KW = (
    "纳斯达克", "纳指", "标普", "日经", "恒生", "恒指", "H股", "中概",
    "港股", "德国", "法国", "东南亚", "越南", "印度", "沙特", "韩国",
)
_BROAD_KW = (
    "沪深300", "中证500", "中证1000", "上证50", "创业板", "科创",
    "红利", "深证100", "中证A",
)

_CODE_PREFIX: dict[str, AssetClass] = {
    "511": AssetClass.BOND,
    "518": AssetClass.COMMODITY,
    "513": AssetClass.CROSS_BORDER,
}


def classify_etf(code: str, name: str) -> AssetClass:
    if code in _EXPLICIT:
        return _EXPLICIT[code]
    if any(kw in name for kw in _EXCLUDED_KW):
        return AssetClass.EXCLUDED
    prefix = code.split(".")[0][:3]
    if prefix in _CODE_PREFIX:
        return _CODE_PREFIX[prefix]
    if any(kw in name for kw in _COMMODITY_KW):
        return AssetClass.COMMODITY
    if any(kw in name for kw in _BOND_KW):
        return AssetClass.BOND
    if any(kw in name for kw in _CROSS_BORDER_KW):
        return AssetClass.CROSS_BORDER
    if any(kw in name for kw in _BROAD_KW):
        return AssetClass.EQUITY_BROAD
    return AssetClass.EQUITY_SECTOR


def classify_universe(
    symbols: list[str], names: dict[str, str],
) -> dict[AssetClass, list[str]]:
    result: dict[AssetClass, list[str]] = {
        c: [] for c in AssetClass if c != AssetClass.EXCLUDED
    }
    for sym in symbols:
        cls = classify_etf(sym, names.get(sym, ""))
        if cls != AssetClass.EXCLUDED:
            result[cls].append(sym)
    return result
