"""adidas Lebanon sitemap + product-page scraper."""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from scraping.common.http import build_session, get_text
from scraping.common.models import ScrapedProductRecord
from scraping.common.normalization import (
    clean_text,
    competitor_product_id,
    discount_pct,
    infer_gender_target,
    normalize_identifier,
    parse_float,
    unique_preserve_order,
    utc_timestamp,
)


COMPETITOR_NAME = "adidas_lb"
BASE_URL = "https://www.adidas.com.lb"
SITEMAP_INDEX_URL = f"{BASE_URL}/sitemap_index.xml"
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
PID_STYLE_RE = re.compile(r"\bA\d+_([A-Z0-9]+)_", re.IGNORECASE)
TEXT_STYLE_RE = re.compile(r"Product\s*Code\s*:?\s*([A-Z0-9-]{5,})", re.IGNORECASE)
DEFAULT_FETCH_WORKERS = 12
MAX_FETCH_WORKERS = 32
_THREAD_LOCAL = threading.local()


def scrape(max_products: int | None = 3, max_pages: int | None = None):
    session = build_session()
    product_urls = _collect_product_urls(session, max_products=max_products, max_sitemaps=max_pages)
    workers = min(_fetch_worker_count(), len(product_urls))
    if workers <= 1:
        for source_url in product_urls:
            yield _fetch_product_record(source_url)
        return

    with ThreadPoolExecutor(max_workers=workers) as executor:
        yield from executor.map(_fetch_product_record, product_urls)


def _fetch_worker_count() -> int:
    raw_value = os.getenv("ADIDAS_LB_FETCH_WORKERS")
    if not raw_value:
        return DEFAULT_FETCH_WORKERS
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_FETCH_WORKERS
    return max(1, min(value, MAX_FETCH_WORKERS))


def _worker_session():
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = build_session()
        _THREAD_LOCAL.session = session
    return session


def _fetch_product_record(source_url: str) -> ScrapedProductRecord:
    try:
        html = get_text(_worker_session(), source_url)
    except RuntimeError:
        return _error_record(source_url)
    return parse_product_page_html(html, source_url)


def _collect_product_urls(session, *, max_products: int | None, max_sitemaps: int | None) -> list[str]:
    index_xml = get_text(session, SITEMAP_INDEX_URL)
    root = ET.fromstring(index_xml)
    product_sitemaps = [
        (node.text or "").strip()
        for node in root.findall("sm:sitemap/sm:loc", SITEMAP_NS)
        if node.text and "product" in node.text.lower()
    ]
    if max_sitemaps is not None and max_sitemaps > 0:
        product_sitemaps = product_sitemaps[:max_sitemaps]

    product_urls: list[str] = []
    for sitemap_url in product_sitemaps:
        product_xml = get_text(session, sitemap_url)
        product_root = ET.fromstring(product_xml)
        product_urls.extend(
            (node.text or "").strip()
            for node in product_root.findall("sm:url/sm:loc", SITEMAP_NS)
            if node.text and node.text.endswith(".html")
        )
        if max_products is not None and len(product_urls) >= max_products:
            break

    return product_urls[:max_products] if max_products is not None else product_urls


def parse_product_page_html(html: str, source_url: str) -> ScrapedProductRecord:
    product_json = _extract_product_json(html)
    product_name = clean_text(_json_value(product_json, "name") or _extract_heading(html))
    product_pid = clean_text(_json_value(product_json, "productID") or _json_value(product_json, "sku") or _extract_data_pid(html))
    style_code = _extract_style_code(html, product_pid, source_url)
    regular_price, sale_price, currency = _extract_price(product_json, html)
    sizes = _extract_sizes(html)
    breadcrumbs = _extract_breadcrumbs(html)
    category = breadcrumbs[-1] if breadcrumbs else None
    availability = _extract_availability(product_json, html, sizes)

    return ScrapedProductRecord(
        competitor_product_id=competitor_product_id(COMPETITOR_NAME, product_pid or source_url),
        competitor_name=COMPETITOR_NAME,
        style_code=normalize_identifier(style_code),
        sku_id=normalize_identifier(product_pid or _json_value(product_json, "sku")),
        brand_name="Adidas",
        product_name=product_name,
        category=category,
        gender_target=infer_gender_target(product_name, source_url, " ".join(breadcrumbs)),
        competitor_price=regular_price,
        competitor_sale_price=sale_price,
        discount_pct=discount_pct(regular_price, sale_price),
        is_on_sale=sale_price is not None,
        availability=availability,
        currency=currency,
        sizes_available=sizes,
        source_url=source_url,
        scraped_at=utc_timestamp(),
        data_valid=bool(product_pid and product_name and regular_price is not None),
    )


def _error_record(source_url: str) -> ScrapedProductRecord:
    product_pid = _extract_pid_from_url(source_url)
    return ScrapedProductRecord(
        competitor_product_id=competitor_product_id(COMPETITOR_NAME, product_pid or source_url),
        competitor_name=COMPETITOR_NAME,
        style_code=normalize_identifier(_extract_style_code("", product_pid, source_url)),
        sku_id=normalize_identifier(product_pid),
        brand_name="Adidas",
        product_name=None,
        category=None,
        gender_target=infer_gender_target(source_url),
        competitor_price=None,
        competitor_sale_price=None,
        discount_pct=None,
        is_on_sale=False,
        availability="unknown",
        currency=None,
        sizes_available=[],
        source_url=source_url,
        scraped_at=utc_timestamp(),
        data_valid=False,
    )


def _extract_pid_from_url(source_url: str) -> str | None:
    match = re.search(r"/([^/]+)\.html(?:$|\?)", source_url)
    return match.group(1) if match else None


def _extract_product_json(html: str) -> dict | None:
    for match in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
        raw = html_lib.unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for candidate in payload if isinstance(payload, list) else [payload]:
            if isinstance(candidate, dict) and str(candidate.get("@type", "")).lower() == "product":
                return candidate
    return None


def _json_value(payload: dict | None, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    return str(value) if value not in (None, "") else None


def _extract_heading(html: str) -> str | None:
    match = re.search(r"<h1[^>]*>.*?<span[^>]*>(.*?)</span>.*?</h1>", html, re.S | re.I)
    if match:
        return _strip_tags(match.group(1))
    match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    return _strip_tags(match.group(1)) if match else None


def _extract_data_pid(html: str) -> str | None:
    match = re.search(r'data-pid=["\']([^"\']+)["\']', html, re.I)
    return match.group(1) if match else None


def _extract_style_code(html: str, product_pid: str | None, source_url: str) -> str | None:
    text_match = TEXT_STYLE_RE.search(_strip_tags(html))
    if text_match:
        return text_match.group(1).upper()
    for value in (product_pid, source_url):
        if not value:
            continue
        pid_match = PID_STYLE_RE.search(value.upper())
        if pid_match:
            return pid_match.group(1).upper()
    return None


def _extract_price(product_json: dict | None, html: str) -> tuple[float | None, float | None, str | None]:
    offers = product_json.get("offers") if isinstance(product_json, dict) else None
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    current_price = parse_float(offers.get("price")) if isinstance(offers, dict) else None
    currency = clean_text(offers.get("priceCurrency")) if isinstance(offers, dict) else None

    regular_price = None
    strike_match = re.search(
        r'strike-through.*?<span[^>]+class=["\'][^"\']*value[^"\']*["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.S | re.I,
    )
    if strike_match:
        regular_price = parse_float(strike_match.group(1))

    if regular_price is not None and current_price is not None and regular_price > current_price:
        return regular_price, current_price, currency
    return current_price or regular_price, None, currency


def _extract_sizes(html: str) -> list[str]:
    sizes: list[str] = []
    for match in re.finditer(r'<button[^>]*class=["\'][^"\']*size-select[^"\']*["\'][^>]*>.*?</button>', html, re.S | re.I):
        button_html = match.group(0)
        value = _extract_attr(button_html, "data-convertedvalue") or _extract_attr(button_html, "data-value")
        if not value:
            value = _strip_tags(button_html)
        sizes.append(value)
    return unique_preserve_order(sizes)


def _extract_breadcrumbs(html: str) -> list[str]:
    breadcrumbs: list[str] = []
    breadcrumb_block = _extract_breadcrumb_block(html)
    for match in re.finditer(r'<a[^>]+href=["\']/en/[^"\']*["\'][^>]*>(.*?)</a>', breadcrumb_block, re.S | re.I):
        value = clean_text(_strip_tags(match.group(1)))
        if value and value.lower() not in {"home"}:
            breadcrumbs.append(value)
    return breadcrumbs


def _extract_breadcrumb_block(html: str) -> str:
    match = re.search(r'<div[^>]+class=["\'][^"\']*breadcrumb-main-block[^"\']*["\'][^>]*>(.*?)</div>', html, re.S | re.I)
    return match.group(1) if match else html


def _extract_availability(product_json: dict | None, html: str, sizes: list[str]) -> str:
    offers = product_json.get("offers") if isinstance(product_json, dict) else None
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    availability = str(offers.get("availability", "")).lower() if isinstance(offers, dict) else ""
    lowered = _strip_tags(html).lower()
    if "outofstock" in availability or "sold out" in lowered:
        return "out_of_stock"
    if "instock" in availability or sizes:
        return "in_stock"
    return "unknown"


def _extract_attr(fragment: str, attr_name: str) -> str | None:
    match = re.search(rf'{re.escape(attr_name)}=["\']([^"\']+)["\']', fragment, re.I)
    return html_lib.unescape(match.group(1)) if match else None


def _strip_tags(value: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", " ", value)).replace("\r", " ").replace("\n", " ").strip()
