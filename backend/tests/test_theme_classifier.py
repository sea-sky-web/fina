from app.services.theme_classifier import infer_etf_theme


def test_infer_etf_theme_from_name() -> None:
    assert infer_etf_theme("沪深300ETF华泰柏瑞") == "宽基指数"
    assert infer_etf_theme("半导体设备ETF国泰") == "半导体芯片"
    assert infer_etf_theme("港股通创新药ETF易方达") == "港股中概"
    assert infer_etf_theme("货币ETF易方达") == "货币现金"
    assert infer_etf_theme("未知ETF") == "其他"
