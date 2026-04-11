"""
StylePulse AI Engine — orchestrates all analyzers and generates the report.

Loads data, runs each analyzer in sequence (each feeding into the next),
then generates both JSON and markdown reports.
"""

import csv
import json
from pathlib import Path

from .analyzers import inventory as inv_analyzer
from .analyzers import competitor as comp_analyzer
from .analyzers import financial as fin_analyzer
from .analyzers import promotions as promo_analyzer
from .report import generator as report_gen


DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "real"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "reports"


def load_csv(path):
    """Load a CSV file as a list of dicts."""
    if not path.exists():
        raise FileNotFoundError(f"Required data file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_json(path):
    """Load a JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"Required data file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run(data_dir=None, output_dir=None):
    """
    Run the full StylePulse AI analysis pipeline.

    Args:
        data_dir: directory containing products.csv, inventory.csv,
                  competitor_prices.csv, financial_profile.json, etc.
        output_dir: directory to write report.json and report.md

    Returns:
        dict with all analysis results
    """
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR

    print("=" * 60)
    print("StylePulse AI — Retail Intelligence Engine")
    print("=" * 60)

    # ── Load Data ──────────────────────────────────────────────────────
    print("\n📂 Loading data...")
    products = load_csv(data_dir / "products.csv")
    inventory = load_csv(data_dir / "inventory.csv")
    competitor_prices = load_csv(data_dir / "competitor_prices.csv")
    financial_profile = load_json(data_dir / "financial_profile.json")
    balance_sheet = load_csv(data_dir / "balance_sheet.csv")
    cashflow = load_csv(data_dir / "cashflow_template.csv")

    print(f"  Products:          {len(products)}")
    print(f"  Inventory rows:    {len(inventory)}")
    print(f"  Competitor prices: {len(competitor_prices)}")

    # ── Run Analyzers ──────────────────────────────────────────────────
    print("\n🔍 Analyzing inventory health...")
    inventory_results = inv_analyzer.analyze(products, inventory, financial_profile)
    inv_metrics = inventory_results["metrics"]
    print(f"  Total SKUs: {inv_metrics['total_skus']}, "
          f"Dead stock: {inv_metrics['dead_stock_pct']:.1f}%, "
          f"Critical stockouts: {inv_metrics['critical_stockout_skus']}")

    print("\n📊 Analyzing competitive positioning...")
    competitor_results = comp_analyzer.analyze(products, competitor_prices, inventory_results)
    comp_overview = competitor_results["market_overview"]
    print(f"  Products matched: {comp_overview['products_analyzed']}, "
          f"Overpriced: {comp_overview['products_overpriced']}, "
          f"Underpriced: {comp_overview['products_underpriced']}")

    print("\n💰 Analyzing financial health...")
    financial_results = fin_analyzer.analyze(
        financial_profile, balance_sheet, cashflow, inventory_results
    )
    fin_cf = financial_results["cashflow_health"]
    print(f"  Cash runway: {fin_cf['cash_runway_months']:.1f} months, "
          f"Status: {fin_cf['runway_status']}")

    print("\n📋 Generating promotion directives...")
    promotion_results = promo_analyzer.analyze(
        products, inventory_results, competitor_results, financial_results
    )
    promo_summary = promotion_results["summary"]
    print(f"  Hold: {promo_summary['hold_count']}, "
          f"Promote: {promo_summary['promote_count']}, "
          f"Markdown: {promo_summary['markdown_count']}, "
          f"Clear: {promo_summary['clearance_count']}")

    # ── Assemble Results ───────────────────────────────────────────────
    analysis_results = {
        "inventory": inventory_results,
        "competitor": competitor_results,
        "financial": financial_results,
        "promotions": promotion_results,
        "metadata": {
            "data_dir": str(data_dir),
            "products_count": len(products),
            "competitor_records": len(competitor_prices),
            "engine_version": "1.0.0",
        },
    }

    # ── Generate Reports ───────────────────────────────────────────────
    print("\n📝 Generating reports...")
    json_path, md_path = report_gen.generate(analysis_results, output_dir)

    print("\n" + "=" * 60)
    print("✅ StylePulse AI analysis complete.")
    print(f"   JSON report: {json_path}")
    print(f"   Advisor report: {md_path}")
    print("=" * 60)

    return analysis_results
