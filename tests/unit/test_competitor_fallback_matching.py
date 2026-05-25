import pandas as pd

from services.decision_intelligence.features import clean_competitors

MATCH_SCORE_THRESHOLD = clean_competitors.MATCH_SCORE_THRESHOLD
filter_to_catalog_products = clean_competitors.filter_to_catalog_products
aggregate_competitor_rows = clean_competitors.aggregate_competitor_rows


def _catalog_row(**overrides):
    row = {
        "sku_id": "SKU-1",
        "catalog_brand": "Adidas",
        "catalog_style_code": "ABC123",
        "retail_price_usd": 100.0,
        "catalog_product_name": "Adidas Ultraboost Running Shoes Men",
        "brand_normalized": "ADIDAS",
        "style_code_normalized": "ABC123",
        "category_normalized": "footwear",
        "gender_normalized": "men",
        "product_key": "ADIDAS|ABC123",
    }
    row.update(overrides)
    return row


def _competitor_row(**overrides):
    row = {
        "brand_name": "ADIDAS",
        "style_code": "ZZZ999",
        "competitor_name": "mikesport",
        "product_name": "Adidas Ultraboost Running Shoes Men",
        "category_normalized": "footwear",
        "gender_normalized": "men",
        "competitor_price": 100.0,
        "competitor_sale_price": pd.NA,
        "discount_pct": pd.NA,
        "is_on_sale": False,
        "availability": "IN_STOCK",
        "currency": "USD",
        "competitor_price_usd": 100.0,
        "competitor_sale_price_usd": pd.NA,
        "effective_competitor_price_usd": 100.0,
        "source_url": "https://example.com/product",
        "scraped_at": pd.Timestamp("2026-04-10T12:00:00Z"),
        "product_key": "ADIDAS|ZZZ999",
    }
    row.update(overrides)
    return row


def test_exact_style_match_wins_over_fallback_candidate():
    products = pd.DataFrame([_catalog_row()])
    competitors = pd.DataFrame(
        [
            _competitor_row(
                style_code="ABC123",
                product_key="ADIDAS|ABC123",
                competitor_name="exact_shop",
                product_name="Different Adidas Product",
            ),
            _competitor_row(
                competitor_name="fallback_shop",
                product_name="Adidas Ultraboost Running Shoes Men",
            ),
        ]
    )

    matched, coverage = filter_to_catalog_products(competitors, products)

    assert coverage["exact_matched_product_keys"] == 1
    assert coverage["fallback_matched_product_keys"] == 0
    assert set(matched["competitor_name"]) == {"exact_shop"}
    assert matched["match_type"].unique().tolist() == ["exact_style"]
    assert matched["match_score"].unique().tolist() == [1.0]


def test_fallback_score_above_threshold_is_accepted():
    products = pd.DataFrame([_catalog_row(product_key="ADIDAS|NOEXACT", style_code_normalized="NOEXACT")])
    competitors = pd.DataFrame([_competitor_row(product_key="ADIDAS|OTHER")])

    matched, coverage = filter_to_catalog_products(competitors, products)

    assert MATCH_SCORE_THRESHOLD == 0.60
    assert coverage["fallback_matched_product_keys"] == 1
    assert matched.iloc[0]["match_score"] > 0.60
    assert matched.iloc[0]["match_type"] == "same_model_family"
    assert matched.iloc[0]["sku_id"] == "SKU-1"


def test_fallback_score_at_or_below_threshold_is_rejected():
    products = pd.DataFrame(
        [
            _catalog_row(
                product_key="ADIDAS|NOEXACT",
                style_code_normalized="NOEXACT",
                catalog_product_name="Adidas Ultraboost Running Shoes Men",
            )
        ]
    )
    competitors = pd.DataFrame(
        [
            _competitor_row(
                product_key="ADIDAS|OTHER",
                product_name="Adidas Campus Lifestyle Sneakers Men",
                effective_competitor_price_usd=1000.0,
                competitor_price_usd=1000.0,
                competitor_price=1000.0,
            )
        ]
    )

    matched, coverage = filter_to_catalog_products(competitors, products)

    assert matched.empty
    assert coverage["matched_product_keys"] == 0
    assert coverage["products_with_no_match"] == 1


def test_fallback_score_equal_to_threshold_is_rejected(monkeypatch):
    products = pd.DataFrame([_catalog_row(product_key="ADIDAS|NOEXACT", style_code_normalized="NOEXACT")])
    competitors = pd.DataFrame([_competitor_row(product_key="ADIDAS|OTHER")])

    monkeypatch.setattr(
        clean_competitors,
        "score_fallback_match",
        lambda product_row, competitor_row: ("similar_product", 0.60, "test boundary"),
    )

    matched, coverage = filter_to_catalog_products(competitors, products)

    assert matched.empty
    assert coverage["matched_product_keys"] == 0
    assert coverage["products_with_no_match"] == 1


def test_missing_safe_key_product_can_use_fallback_match():
    products = pd.DataFrame(
        [
            _catalog_row(
                catalog_style_code=pd.NA,
                style_code_normalized=None,
                product_key="SKU|SKU-1",
                product_key_source="sku_fallback",
            )
        ]
    )
    competitors = pd.DataFrame([_competitor_row(product_key="ADIDAS|OTHER")])

    matched, coverage = filter_to_catalog_products(competitors, products)
    aggregated = aggregate_competitor_rows(matched)

    assert coverage["products_missing_safe_key"] == 1
    assert coverage["fallback_matched_product_keys"] == 1
    assert matched.iloc[0]["match_score"] > 0.60
    assert aggregated.iloc[0]["product_key"] == "SKU|SKU-1"
    assert aggregated.iloc[0]["has_competitor_data"] == 1
