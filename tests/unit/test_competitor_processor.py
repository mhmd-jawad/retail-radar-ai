import pandas as pd

from services.decision_intelligence.features import clean_competitors
from services.market_intelligence import competitor_processor


def _product(**overrides):
    product = {
        "sku_id": "SKU-1",
        "product_name": "Adidas Ultraboost Running Shoes Men",
        "brand": "Adidas",
        "style_code": "ABC123",
        "category": "footwear",
        "gender": "men",
        "retail_price_usd": 100.0,
    }
    product.update(overrides)
    return product


def _competitor(**overrides):
    row = {
        "brand_name": "Adidas",
        "style_code": "ABC123",
        "competitor_name": "mikesport",
        "product_name": "Adidas Ultraboost Running Shoes Men",
        "category": "footwear",
        "gender_target": "men",
        "competitor_price": 80.0,
        "competitor_sale_price": pd.NA,
        "discount_pct": pd.NA,
        "is_on_sale": False,
        "availability": "in_stock",
        "currency": "USD",
        "source_url": "https://example.com/product",
        "scraped_at": "2026-04-10T12:00:00Z",
        "data_valid": True,
    }
    row.update(overrides)
    return row


def test_exact_style_match_builds_competitor_signals():
    signals = competitor_processor.build_competitor_signals_for_product(
        _product(),
        competitor_rows=[_competitor()],
    )

    assert signals["sku_id"] == "SKU-1"
    assert signals["num_competitors_tracked"] == 1
    assert signals["competitor_min_price"] == 80.0
    assert signals["price_gap_pct"] == 0.2
    assert signals["fallback_used"] is False


def test_missing_style_product_can_use_fallback_match():
    signals = competitor_processor.build_competitor_signals_for_product(
        _product(
            style_code=None,
            product_key="Adidas|NAME:ADIDAS ULTRABOOST RUNNING SHOES MEN",
        ),
        competitor_rows=[_competitor(style_code="ZZZ999")],
    )

    assert signals["num_competitors_tracked"] == 1
    assert signals["competitor_min_price"] == 80.0
    assert signals["fallback_used"] is False


def test_fallback_score_equal_to_threshold_is_no_match(monkeypatch):
    monkeypatch.setattr(
        clean_competitors,
        "score_fallback_match",
        lambda product_row, competitor_row: ("similar_product", 0.60, "test boundary"),
    )

    signals = competitor_processor.build_competitor_signals_for_product(
        _product(style_code=None, product_key="Adidas|NAME:BOUNDARY"),
        competitor_rows=[_competitor(style_code="ZZZ999")],
    )

    assert signals["num_competitors_tracked"] == 0
    assert signals["price_gap_pct"] == 0.0
    assert signals["fallback_used"] is True
    assert signals["fallback_reason"] == competitor_processor.NO_MATCH_REASON


def test_no_reliable_match_returns_no_competitor_signals():
    signals = competitor_processor.build_competitor_signals_for_product(
        _product(brand="Mizuno", style_code="MIZ-1"),
        competitor_rows=[_competitor(brand_name="Adidas")],
    )

    assert signals["competitor_min_price"] == 0.0
    assert signals["competitor_avg_price"] == 0.0
    assert signals["num_competitors_tracked"] == 0
    assert signals["confidence_score"] == 0.0
    assert signals["fallback_used"] is True
