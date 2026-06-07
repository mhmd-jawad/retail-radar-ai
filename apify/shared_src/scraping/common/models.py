"""Normalized scraped product schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any


SCRAPED_PRODUCT_FIELDS = [
    "competitor_product_id",
    "competitor_name",
    "style_code",
    "brand_name",
    "product_name",
    "category",
    "gender_target",
    "competitor_price",
    "competitor_sale_price",
    "discount_pct",
    "is_on_sale",
    "availability",
    "currency",
    "sizes_available",
    "source_url",
    "scraped_at",
    "data_valid",
]


@dataclass(slots=True)
class ScrapedProductRecord:
    competitor_product_id: str
    competitor_name: str
    style_code: str | None
    brand_name: str | None
    product_name: str | None
    category: str | None
    gender_target: str | None
    competitor_price: float | None
    competitor_sale_price: float | None
    discount_pct: float | None
    is_on_sale: bool
    availability: str | None
    currency: str | None
    sizes_available: list[str] = field(default_factory=list)
    source_url: str = ""
    scraped_at: str = ""
    data_valid: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_csv_row(self) -> dict[str, Any]:
        row = self.to_dict()
        row["sizes_available"] = json.dumps(self.sizes_available, ensure_ascii=True)
        return row

