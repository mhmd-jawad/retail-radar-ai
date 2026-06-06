from eep.apify_ingest import _dedupe_items


def test_dedupe_items_prefers_competitor_product_id():
    first = {
        "competitor_product_id": "adidas_lb:A123",
        "source_url": "https://www.adidas.com.lb/a.html",
        "product_name": "First",
    }
    duplicate = {
        "competitor_product_id": "adidas_lb:A123",
        "source_url": "https://www.adidas.com.lb/a.html",
        "product_name": "Duplicate",
    }
    second = {
        "competitor_product_id": "adidas_lb:B456",
        "source_url": "https://www.adidas.com.lb/b.html",
        "product_name": "Second",
    }

    assert _dedupe_items([first, duplicate, second]) == [first, second]


def test_dedupe_items_falls_back_to_source_url():
    first = {
        "source_url": "https://www.adidas.com.lb/a.html",
        "product_name": "First",
    }
    duplicate = {
        "source_url": "https://www.adidas.com.lb/a.html",
        "product_name": "Duplicate",
    }

    assert _dedupe_items([first, duplicate]) == [first]
