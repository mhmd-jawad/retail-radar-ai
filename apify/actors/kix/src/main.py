from __future__ import annotations

import csv
import importlib
import io
import os
import sys
from pathlib import Path

from apify import Actor


def _bootstrap_shared_path() -> None:
    shared_override = os.getenv("APIFY_SHARED_SRC")
    candidates = []
    if shared_override:
        candidates.append(Path(shared_override))
    candidates.append(Path(__file__).resolve().parents[1] / "shared_src")
    candidates.append(Path(__file__).resolve().parents[3] / "shared_src")

    for candidate in candidates:
        if candidate.exists():
            candidate_str = str(candidate.resolve())
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return

    raise RuntimeError("Could not locate shared scraper package for this actor.")


_bootstrap_shared_path()

from scraping.common.models import SCRAPED_PRODUCT_FIELDS
from scraping.common.normalization import has_real_identifier


def _store_name() -> str:
    store_name = os.getenv("STORE_NAME")
    if store_name:
        return store_name

    inferred = Path(__file__).resolve().parents[1].name
    if inferred:
        return inferred
    raise RuntimeError("STORE_NAME environment variable is required.")


def _load_scrape_callable(store_name: str):
    module = importlib.import_module(f"scraping.shops.{store_name}.scraper")
    scrape = getattr(module, "scrape", None)
    if scrape is None:
        raise RuntimeError(f"scraping.shops.{store_name}.scraper has no scrape() function.")
    return scrape


def _positive_int(value, *, field_name: str, allow_none: bool = True):
    if value in (None, ""):
        if allow_none:
            return None
        raise ValueError(f"{field_name} is required.")

    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return parsed


def _records_to_csv(records) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=SCRAPED_PRODUCT_FIELDS)
    writer.writeheader()
    for record in records:
        writer.writerow(record.to_csv_row())
    return buffer.getvalue()


async def _consume_records(records_iterable, *, chunk_size: int = 100):
    records = []
    items: list[dict] = []
    chunk: list[dict] = []

    for record in records_iterable:
        records.append(record)
        item = record.to_dict()
        items.append(item)
        chunk.append(item)
        if len(chunk) >= chunk_size:
            await Actor.push_data(chunk)
            chunk = []

    if chunk:
        await Actor.push_data(chunk)

    return records, items


def _build_summary(store_name: str, records, *, full: bool, sample_size: int | None, max_pages: int | None) -> dict:
    return {
        "shop": store_name,
        "mode": "full" if full else "sample",
        "sample_size": sample_size,
        "max_pages": max_pages,
        "record_count": len(records),
        "valid_count": sum(1 for record in records if record.data_valid),
        "style_code_count": sum(1 for record in records if has_real_identifier(record.style_code)),
        "sku_id_count": sum(1 for record in records if has_real_identifier(record.sku_id)),
        "sale_count": sum(1 for record in records if record.is_on_sale),
        "out_of_stock_count": sum(1 for record in records if record.availability == "out_of_stock"),
    }


async def main() -> None:
    async with Actor:
        store_name = _store_name()
        actor_input = await Actor.get_input() or {}
        full = bool(actor_input.get("full", False))
        sample_size = _positive_int(actor_input.get("sampleSize", 3), field_name="sampleSize", allow_none=False)
        max_pages = _positive_int(actor_input.get("maxPages"), field_name="maxPages", allow_none=True)
        max_products = None if full else sample_size
        scrape = _load_scrape_callable(store_name)

        await Actor.set_status_message(
            f"Scraping {store_name} in {'full' if full else 'sample'} mode",
        )
        records, items = await _consume_records(scrape(max_products=max_products, max_pages=max_pages))
        summary = _build_summary(
            store_name,
            records,
            full=full,
            sample_size=sample_size,
            max_pages=max_pages,
        )

        if actor_input.get("saveSummaryToKeyValueStore", True):
            await Actor.set_value("OUTPUT_SUMMARY", summary)
        if actor_input.get("saveJsonToKeyValueStore", True):
            await Actor.set_value("OUTPUT_JSON", items)
        if actor_input.get("saveCsvToKeyValueStore", True):
            await Actor.set_value(
                "OUTPUT_CSV",
                _records_to_csv(records),
                content_type="text/csv; charset=utf-8",
            )

        await Actor.set_status_message(
            f"Finished {store_name}: {len(records)} records, {summary['valid_count']} valid",
            is_terminal=True,
        )
