from datetime import datetime, timezone

import pandas as pd
import psycopg
import pytest

from eep import frontend_bridge
from services.market_intelligence import competitor_processor


def test_ops_scrape_runs_use_database_rows_when_available(monkeypatch):
    timestamp = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        frontend_bridge,
        "_read_intel_rows",
        lambda query, params=(): [
            {
                "id": 8,
                "shop_code": "adidas_lb",
                "item_count": 10102,
                "ingest_status": "succeeded",
                "started_at": timestamp,
                "finished_at": timestamp,
                "created_at": timestamp,
            }
        ],
    )

    assert frontend_bridge.build_scrape_runs() == [
        {
            "id": "8",
            "shop": "adidas_lb",
            "started_at": timestamp.isoformat(),
            "finished_at": timestamp.isoformat(),
            "status": "success",
            "items_scraped": 10102,
            "valid_rows": 10102,
        }
    ]


def test_ops_competitor_latest_use_database_rows_when_available(monkeypatch):
    timestamp = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        frontend_bridge,
        "_read_intel_rows",
        lambda query, params=(): [
            {
                "shop_code": "tchooz",
                "product_key": "shoe-1",
                "competitor_product_id": None,
                "product_name": "Runner",
                "brand_name": "Adidas",
                "price_usd": 80,
                "is_on_sale": True,
                "availability": "in_stock",
                "source_url": "https://example.test/runner",
                "last_seen_at": timestamp,
            }
        ],
    )

    row = frontend_bridge.build_competitor_latest(limit=1)[0]
    assert row["shop"] == "tchooz"
    assert row["external_id"] == "shoe-1"
    assert row["price_usd"] == 80.0
    assert row["in_stock"] is True


def test_model_competitor_source_prefers_live_database(monkeypatch):
    database_rows = pd.DataFrame(
        [
            {
                "brand_name": "Adidas",
                "style_code": "GX1000",
                "competitor_name": "tchooz",
                "product_name": "Runner",
                "category": "footwear",
                "gender_target": "unisex",
                "competitor_price": 80,
                "competitor_sale_price": 75,
                "discount_pct": 6.25,
                "is_on_sale": True,
                "availability": "in_stock",
                "currency": "USD",
                "source_url": "https://example.test/runner",
                "scraped_at": "2026-05-27T10:00:00+00:00",
                "data_valid": True,
            }
        ]
    )
    monkeypatch.setattr(competitor_processor, "_load_database_competitor_rows", lambda: database_rows)
    monkeypatch.setattr(
        competitor_processor.matcher,
        "load_scraped_competitors",
        lambda: (_ for _ in ()).throw(AssertionError("file fallback must not be used")),
    )

    rows = competitor_processor.load_live_competitor_rows()

    assert len(rows) == 1
    assert rows.iloc[0]["competitor_name"] == "tchooz"


def test_configured_database_failure_does_not_fall_back_to_file_data(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured/database")
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("database unavailable")),
    )

    with pytest.raises(RuntimeError, match="configured PostgreSQL"):
        frontend_bridge._read_intel_rows("select 1")
