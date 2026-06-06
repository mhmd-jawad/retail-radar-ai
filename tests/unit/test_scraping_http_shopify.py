from __future__ import annotations

import sys
from pathlib import Path

import requests

ACTOR_SHARED_SRC = Path(__file__).resolve().parents[2] / "apify" / "actors" / "mikesport" / "shared_src"
sys.path.insert(0, str(ACTOR_SHARED_SRC))

from scraping.common import http, shopify


class FakeResponse:
    def __init__(self, status_code: int, *, text: str = "", headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls = 0

    def get(self, url: str, *, timeout: int) -> FakeResponse:
        self.calls += 1
        return self.responses.pop(0)


def test_get_text_retries_429_using_retry_after(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    session = FakeSession(
        [
            FakeResponse(429, headers={"Retry-After": "3"}),
            FakeResponse(200, text="ok"),
        ]
    )

    result = http.get_text(session, "https://example.test/products.json", retries=1)

    assert result == "ok"
    assert sleeps == [3.0]
    assert session.calls == 2


def test_get_text_retries_429_with_long_default_backoff(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    session = FakeSession(
        [
            FakeResponse(429),
            FakeResponse(200, text="ok"),
        ]
    )

    result = http.get_text(session, "https://example.test/products.json", retries=1)

    assert result == "ok"
    assert sleeps == [10.0]


def test_shopify_late_page_429_stops_with_partial_records(monkeypatch) -> None:
    calls: list[str] = []

    def fake_get_json(session, url: str):
        calls.append(url)
        if "page=1" in url:
            return {
                "products": [
                    {
                        "id": 123,
                        "handle": "test-product",
                        "title": "Test Product",
                        "variants": [{"available": True, "price": "10.00", "sku": "SKU-1"}],
                    }
                ]
            }
        raise RuntimeError(
            "Failed to fetch https://example.test/products.json?limit=250&page=2: "
            "429 Client Error: Too Many Requests"
        )

    monkeypatch.setattr(shopify, "build_session", lambda: object())
    monkeypatch.setattr(shopify, "get_json", fake_get_json)

    records = list(
        shopify.scrape_shopify_catalog(
            shopify.ShopifyShopConfig(
                competitor_name="test",
                base_url="https://example.test",
            ),
            max_products=None,
        )
    )

    assert len(records) == 1
    assert records[0].competitor_product_id == "test:123"
    assert len(calls) == 2
