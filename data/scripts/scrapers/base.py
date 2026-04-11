"""
Base scraper class. All site-specific scrapers inherit from this.
Output schema matches data/outputs/adidas_lb_full_records.json exactly.
"""

import asyncio
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
import httpx


# USD/LBP exchange rate — update if needed
LBP_PER_USD = 89_500.0


@dataclass
class ScrapedProduct:
    retailer_name: str
    product_name: str
    style_code: str
    sku_id: Optional[str]
    competitor_name: str
    competitor_price: Optional[float]
    competitor_sale_price: Optional[float]
    is_on_sale: bool
    discount_pct: Optional[float]
    availability: str           # in_stock | low_stock | out_of_stock
    currency: str               # LBP | USD
    colorway: Optional[str]
    category: Optional[str]
    gender_target: Optional[str]
    sizes_available: list
    source_url: str
    scraped_at: str             # ISO8601
    data_valid: bool
    raw_price_text: Optional[str]
    raw_availability_text: Optional[str]
    error_message: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


# Adidas style code pattern: 2 letters + 4 digits  OR  6 alphanumeric chars
STYLE_CODE_RE = re.compile(r'\b([A-Z]{1,3}[0-9]{4,6}|[A-Z0-9]{6})\b')


def extract_style_code(text: str) -> Optional[str]:
    """Find the first Adidas-looking style code in any text blob."""
    if not text:
        return None
    matches = STYLE_CODE_RE.findall(text.upper())
    # Filter out obvious non-codes (pure numbers, too short)
    for m in matches:
        if len(m) >= 5 and not m.isdigit():
            return m
    return None


def lbp_to_usd(lbp: float) -> float:
    return round(lbp / LBP_PER_USD, 2)


def usd_to_lbp(usd: float) -> float:
    return round(usd * LBP_PER_USD, 0)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class BaseCompetitorScraper(ABC):
    """
    Abstract base for all competitor scrapers.
    Subclasses implement `scrape_all_products()` and
    `scrape_by_style_code(style_code)`.
    """

    retailer_name: str       # e.g. "azadea_lb"
    competitor_name: str     # e.g. "Azadea Lebanon"
    base_url: str
    currency: str = "USD"

    # httpx client settings
    TIMEOUT = 20.0
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/json,*/*",
    }

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            headers=self.HEADERS,
            timeout=self.TIMEOUT,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_):
        if self._client:
            await self._client.aclose()

    @abstractmethod
    async def scrape_all_products(self) -> list[ScrapedProduct]:
        """
        Download the full product catalog from this competitor.
        Used for the nightly full refresh.
        """
        ...

    @abstractmethod
    async def scrape_by_style_code(self, style_code: str) -> Optional[ScrapedProduct]:
        """
        Look up a specific style code on this competitor's site.
        Returns None if not found or scrape fails.
        """
        ...

    async def get(self, url: str, **kwargs) -> httpx.Response:
        assert self._client, "Use as async context manager"
        await asyncio.sleep(0.5)   # polite delay between requests
        return await self._client.get(url, **kwargs)

    def make_error_product(self, style_code: str, url: str, error: str) -> ScrapedProduct:
        return ScrapedProduct(
            retailer_name=self.retailer_name,
            product_name="",
            style_code=style_code,
            sku_id=None,
            competitor_name=self.competitor_name,
            competitor_price=None,
            competitor_sale_price=None,
            is_on_sale=False,
            discount_pct=None,
            availability="unknown",
            currency=self.currency,
            colorway=None,
            category=None,
            gender_target=None,
            sizes_available=[],
            source_url=url,
            scraped_at=now_iso(),
            data_valid=False,
            raw_price_text=None,
            raw_availability_text=None,
            error_message=error,
        )
