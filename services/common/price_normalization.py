from __future__ import annotations

import os
from typing import Any

DEFAULT_LBP_TO_USD_RATE = 90_000.0
LBP_LIKE_PRICE_THRESHOLD = 10_000.0
MAX_REASONABLE_USD_PRICE = 10_000.0


def lbp_to_usd_rate() -> float:
    """Return the configured LBP/USD rate, falling back to a conservative default."""
    try:
        value = float(os.environ.get("LBP_TO_USD_RATE", DEFAULT_LBP_TO_USD_RATE))
    except (TypeError, ValueError):
        value = DEFAULT_LBP_TO_USD_RATE
    return value if value > 0 else DEFAULT_LBP_TO_USD_RATE


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_competitor_price_usd(value: Any, currency: Any = None) -> float | None:
    """
    Normalize scraped competitor prices to USD.

    Some live scraper rows are labeled USD but contain LBP-sized values such as
    14,310,000. Treat those large values as LBP-style prices so downstream
    gap calculations do not produce impossible percentages.
    """
    price = _to_float(value)
    if price is None or price <= 0:
        return None

    currency_code = str(currency or "").strip().upper()
    if currency_code == "LBP" or price >= LBP_LIKE_PRICE_THRESHOLD:
        price = price / lbp_to_usd_rate()

    if price <= 0 or price > MAX_REASONABLE_USD_PRICE:
        return None
    return round(price, 2)


def effective_competitor_price_usd(
    competitor_price: Any,
    competitor_sale_price: Any = None,
    currency: Any = None,
    is_on_sale: Any = None,
) -> float | None:
    sale = normalize_competitor_price_usd(competitor_sale_price, currency)
    regular = normalize_competitor_price_usd(competitor_price, currency)
    sale_flag = str(is_on_sale).strip().lower() in {"1", "true", "yes", "on"} if is_on_sale is not None else False
    return sale if sale_flag and sale is not None else regular or sale


def price_gap_pct(our_price_usd: Any, competitor_price_usd: Any) -> float | None:
    our_price = _to_float(our_price_usd)
    competitor_price = _to_float(competitor_price_usd)
    if our_price is None or competitor_price is None or our_price <= 0 or competitor_price <= 0:
        return None
    gap = (our_price - competitor_price) / our_price * 100
    if abs(gap) > 500:
        return None
    return round(gap, 1)
