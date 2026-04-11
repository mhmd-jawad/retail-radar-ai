"""Command-line runner for the new multi-shop scraper."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib
from pathlib import Path
from typing import Iterable

from scraping.common.models import ScrapedProductRecord
from scraping.common.output import write_records


SHOP_MODULES = {
    "adidas_lb": "scraping.shops.adidas_lb.scraper",
    "mikesport": "scraping.shops.mikesport.scraper",
    "tchooz": "scraping.shops.tchooz.scraper",
    "shoesworld": "scraping.shops.shoesworld.scraper",
    "citysport": "scraping.shops.citysport.scraper",
    "kix": "scraping.shops.kix.scraper",
    "marka_store": "scraping.shops.marka_store.scraper",
}


def main() -> int:
    args = parse_args()
    shops = parse_shop_selection(args.shops)
    max_products = None if args.full else args.sample_size
    output_dir = Path(args.output_dir)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    all_records: list[ScrapedProductRecord] = []
    failures: dict[str, str] = {}

    for shop in shops:
        print(f"Scraping {shop} with max_products={max_products if max_products is not None else 'FULL'}")
        try:
            records = scrape_shop(shop, max_products=max_products, max_pages=args.max_pages)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            import traceback
            traceback.print_exc()
            failures[shop] = f"{type(exc).__name__}: {exc}"
            print(f"  failed: {failures[shop]}")
            continue

        all_records.extend(records)
        shop_paths = write_records(records, output_dir / shop, f"{run_id}_{shop}_records")
        valid_count = sum(1 for record in records if record.data_valid)
        print(f"  records={len(records)} valid={valid_count} csv={shop_paths['csv']}")

    combined_paths = write_records(all_records, output_dir, f"{run_id}_all_records")
    print_summary(all_records, combined_paths, failures)
    return 1 if failures and not all_records else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape normalized competitor product snapshots.")
    parser.add_argument(
        "--shops",
        default="all",
        help="Comma-separated shop list or 'all'. Available: " + ", ".join(SHOP_MODULES),
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=3,
        help="Products per shop in sample mode. Ignored when --full is set.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Scrape full supported catalogs instead of a small sample.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional adapter page/sitemap cap for debugging full runs.",
    )
    parser.add_argument(
        "--output-dir",
        default="scraping/data/outputs",
        help="Directory for CSV and JSON output.",
    )
    return parser.parse_args()


def parse_shop_selection(raw_value: str) -> list[str]:
    if raw_value.strip().lower() == "all":
        return list(SHOP_MODULES)
    shops = [value.strip() for value in raw_value.split(",") if value.strip()]
    unknown = [shop for shop in shops if shop not in SHOP_MODULES]
    if unknown:
        raise SystemExit(f"Unknown shop(s): {', '.join(unknown)}")
    return shops


def scrape_shop(shop: str, *, max_products: int | None, max_pages: int | None) -> list[ScrapedProductRecord]:
    module = importlib.import_module(SHOP_MODULES[shop])
    return list(module.scrape(max_products=max_products, max_pages=max_pages))


def print_summary(
    records: Iterable[ScrapedProductRecord],
    combined_paths: dict[str, Path],
    failures: dict[str, str],
) -> None:
    records = list(records)
    counts = Counter(record.competitor_name for record in records)
    valid_count = sum(1 for record in records if record.data_valid)
    style_code_count = sum(1 for record in records if record.style_code)

    print("\nRun summary")
    print(f"  total_records={len(records)}")
    print(f"  valid_records={valid_count}")
    print(f"  records_with_style_code={style_code_count}")
    for shop, count in counts.items():
        print(f"  {shop}={count}")
    if failures:
        print("  failures:")
        for shop, message in failures.items():
            print(f"    {shop}: {message}")
    print(f"  combined_csv={combined_paths['csv']}")
    print(f"  combined_json={combined_paths['json']}")


if __name__ == "__main__":
    raise SystemExit(main())
