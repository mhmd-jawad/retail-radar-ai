from eep import frontend_bridge


def test_prepare_ie2_request_uses_live_competitor_processor(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        frontend_bridge,
        "load_products_index",
        lambda: {
            "SKU-1": {
                "sku_id": "SKU-1",
                "product_name": "Adidas Ultraboost Running Shoes Men",
                "brand": "Adidas",
                "style_code": "ABC123",
                "system_category": "footwear",
                "retail_price_usd": "100",
                "cost_price_usd": "50",
                "initial_stock": "20",
            }
        },
    )
    monkeypatch.setattr(
        frontend_bridge,
        "load_inventory_index",
        lambda: {"SKU-1": {"current_stock": "10", "retail_price_usd": "100", "cost_price_usd": "50"}},
    )
    monkeypatch.setattr(frontend_bridge, "load_latest_state_index", lambda: {})

    def fake_processor(product):
        captured.update(product)
        return {
            "sku_id": product["sku_id"],
            "competitor_min_price": 80.0,
            "competitor_avg_price": 85.0,
            "price_gap_pct": 0.2,
            "competitors_on_sale_count": 1,
            "competitors_out_of_stock_count": 0,
            "num_competitors_tracked": 2,
            "cheapest_competitor_name": "mikesport",
            "price_trend_direction": "STABLE",
            "data_freshness_hours": 12.0,
            "confidence_score": 0.9,
            "fallback_used": False,
            "fallback_reason": None,
            "timestamp": "2026-04-10T12:00:00",
        }

    monkeypatch.setattr(frontend_bridge, "build_competitor_signals_for_product", fake_processor)

    request = frontend_bridge.prepare_ie2_request("SKU-1", {})

    assert captured["sku_id"] == "SKU-1"
    assert captured["style_code"] == "ABC123"
    assert request["competitor_signals"]["num_competitors_tracked"] == 2
    assert request["competitor_signals"]["price_gap_pct"] == 0.2
