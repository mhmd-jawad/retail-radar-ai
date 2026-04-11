"""
Scraper runner — scrapes all competitors and saves results.

Usage:
    # Scrape all competitors (full catalog)
    python -m data.scripts.scrapers.runner

    # Scrape only specific competitors
    python -m data.scripts.scrapers.runner --sites mikesport_lb comostore_lb

    # Only scrape products matching our existing style codes
    python -m data.scripts.scrapers.runner --matched-only
"""

import asyncio
import argparse
import pandas as pd
from pathlib import Path

from .sites.mikesport_lb import MikeSportLB
from .sites.comostore_lb import ComoStoreLB
from .sites.azadea_lb import AzadeaLB
from .sites.brandsforless_lb import BrandsForLessLB
from .storage import save_all

# All available scrapers
ALL_SCRAPERS = {
    "mikesport_lb":     MikeSportLB,
    "comostore_lb":     ComoStoreLB,
    "azadea_lb":        AzadeaLB,
    "brandsforless_lb": BrandsForLessLB,
}

OUTPUTS_DIR = Path(__file__).parents[2] / "outputs"


def load_known_style_codes() -> set[str]:
    """Load the 577 style codes we already matched from real data."""
    comparison_csv = OUTPUTS_DIR / "adidas_vs_mikesport_style_code_comparison.csv"
    if not comparison_csv.exists():
        print("[runner] Warning: adidas_vs_mikesport_style_code_comparison.csv not found. Using empty set.")
        return set()
    df = pd.read_csv(comparison_csv)
    # The comparison file has a 'style_code' column
    if "style_code" in df.columns:
        codes = set(df["style_code"].dropna().str.upper().tolist())
        print(f"[runner] Loaded {len(codes)} known style codes from comparison file.")
        return codes
    return set()


async def run_scraper(scraper_class, matched_only: bool = False):
    """Run one scraper and save results."""
    name = scraper_class.retailer_name
    print(f"\n{'='*50}")
    print(f"[runner] Starting: {name}")
    print(f"{'='*50}")

    async with scraper_class() as scraper:
        products = await scraper.scrape_all_products()

    if matched_only and products:
        known_codes = load_known_style_codes()
        if known_codes:
            before = len(products)
            products = [p for p in products if p.style_code in known_codes]
            print(f"[runner] {name}: filtered to {len(products)} matched products (was {before})")

    if products:
        save_all(products, name)
        print(f"[runner] {name}: Done. {len(products)} products saved.")
    else:
        print(f"[runner] {name}: No products scraped. Check selectors or site availability.")

    return products


async def run_all(sites: list[str] | None = None, matched_only: bool = False):
    """Run all (or selected) scrapers sequentially."""
    targets = sites or list(ALL_SCRAPERS.keys())
    total = 0
    for site_name in targets:
        if site_name not in ALL_SCRAPERS:
            print(f"[runner] Unknown site: {site_name}. Available: {list(ALL_SCRAPERS.keys())}")
            continue
        products = await run_scraper(ALL_SCRAPERS[site_name], matched_only=matched_only)
        total += len(products)

    print(f"\n[runner] All done. Total products scraped: {total}")


def main():
    parser = argparse.ArgumentParser(description="StylePulse AI competitor scraper")
    parser.add_argument(
        "--sites", nargs="*",
        help=f"Which sites to scrape. Options: {list(ALL_SCRAPERS.keys())}. Default: all."
    )
    parser.add_argument(
        "--matched-only", action="store_true",
        help="Only save products whose style code matches the 577 known codes."
    )
    args = parser.parse_args()

    asyncio.run(run_all(sites=args.sites, matched_only=args.matched_only))


if __name__ == "__main__":
    main()
