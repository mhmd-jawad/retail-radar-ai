"""
build_financials.py — Build Lebanon-adjusted financial model from real inventory data.

Uses products.csv (from build_inventory.py) to derive:
  - Opening balance sheet with Lebanon-specific line items
  - Monthly OpEx structure (fresh dollar basis)
  - Cash flow template
  - Financial profile (JSON) for StylePulse AI engine

Lebanon financial context (2026):
  - Currency: fresh USD (cash outside banking system)
  - Lollar: bank-trapped USD at ~15¢ on the dollar
  - Grid electricity: ~12h/day → generator costs mandatory
  - Import lead times: 3–8 weeks via Beirut port
  - Payment: cash-dominant economy, minimal card processing

Outputs:
  data/real/balance_sheet.csv
  data/real/cashflow_template.csv
  data/real/opex_assumptions.csv
  data/real/financial_profile.json

Usage:
  python data/scripts/build_financials.py
"""

import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS_CSV = ROOT / "data" / "real" / "products.csv"
OUT_DIR = ROOT / "data" / "real"

# ── Lebanon Financial Parameters (2026) ────────────────────────────────────

# Monthly fixed costs (fresh USD equivalent)
MONTHLY_OPEX = {
    "rent": {
        "amount_usd": 1100,
        "type": "fixed_monthly",
        "notes": "60-80 sqm retail space, Beirut suburb or secondary city",
    },
    "salaries_owner": {
        "amount_usd": 800,
        "type": "fixed_monthly",
        "notes": "Owner draw (modest, reinvesting profits)",
    },
    "salaries_staff": {
        "amount_usd": 900,
        "type": "fixed_monthly",
        "notes": "2 part-time staff × $450/mo (fresh dollar equivalent)",
    },
    "generator_fuel": {
        "amount_usd": 220,
        "type": "fixed_monthly",
        "notes": "Grid ~12h/day, generator for remaining hours. Diesel cost.",
    },
    "internet_phone": {
        "amount_usd": 150,
        "type": "fixed_monthly",
        "notes": "Business internet + mobile. Lebanese ISP rates.",
    },
    "utilities_water": {
        "amount_usd": 40,
        "type": "fixed_monthly",
        "notes": "Municipal water + tanker supplement",
    },
    "insurance": {
        "amount_usd": 80,
        "type": "fixed_monthly",
        "notes": "Basic store insurance (fire, theft). Annual $960 amortized.",
    },
    "accounting_legal": {
        "amount_usd": 100,
        "type": "fixed_monthly",
        "notes": "Part-time accountant. Annual $1,200 amortized.",
    },
    "miscellaneous": {
        "amount_usd": 110,
        "type": "fixed_monthly",
        "notes": "Bags, receipts, cleaning, minor repairs",
    },
}

# Variable cost rates
VARIABLE_COSTS = {
    "payment_processing_pct": {
        "rate": 0.015,
        "basis": "revenue",
        "notes": "Low — Lebanon is mostly cash. Only ~15% of sales via card/OMT.",
    },
    "marketing_pct": {
        "rate": 0.035,
        "basis": "revenue",
        "notes": "Instagram ads, WhatsApp Business, local influencer deals.",
    },
    "logistics_pct_of_cogs": {
        "rate": 0.02,
        "basis": "cogs",
        "notes": "Local delivery, supplier pickup runs. No major distribution.",
    },
    "shrinkage_pct": {
        "rate": 0.008,
        "basis": "inventory_at_cost",
        "notes": "Damage, theft, defects. Low for sportswear.",
    },
}

# One-time / setup costs (already spent, reflected in equity)
SETUP_COSTS = {
    "store_fitout": 18000,       # shelving, lighting, signage, flooring
    "security_deposit": 3300,    # 3 months rent
    "pos_system": 800,           # basic POS + receipt printer
    "initial_marketing": 1500,   # grand opening, social media push
    "legal_registration": 500,   # business registration, permits
}

# Lebanon-specific balance sheet items
LOLLAR_BALANCE = 12000   # USD trapped in Lebanese bank (pre-crisis deposit)
LOLLAR_HAIRCUT = 0.15    # real value = 15¢ per dollar
FRESH_DOLLAR_BUFFER_MONTHS = 3  # working capital = 3 months OpEx in cash


def load_products():
    """Load products.csv to compute inventory values."""
    products = []
    with open(PRODUCTS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            products.append(r)
    return products


def compute_inventory_value(products):
    """Compute total inventory at cost and retail."""
    total_cost = sum(float(p["cost_price_usd"]) * int(p["initial_stock"]) for p in products)
    total_retail = sum(float(p["retail_price_usd"]) * int(p["initial_stock"]) for p in products)
    return round(total_cost, 2), round(total_retail, 2)


def compute_monthly_fixed_opex():
    """Sum up all fixed monthly operating expenses."""
    return sum(v["amount_usd"] for v in MONTHLY_OPEX.values())


def build_balance_sheet(inventory_at_cost, inventory_at_retail):
    """
    Build opening balance sheet for a new Lebanese sportswear store.

    Assets = Liabilities + Equity (must balance to $0 difference).
    """
    monthly_fixed = compute_monthly_fixed_opex()
    fresh_buffer = round(monthly_fixed * FRESH_DOLLAR_BUFFER_MONTHS, 2)
    setup_total = sum(SETUP_COSTS.values())
    lollar_real_value = round(LOLLAR_BALANCE * LOLLAR_HAIRCUT, 2)

    # ASSETS
    assets = [
        ("ASSETS", "Cash — Fresh Dollars (operating)", fresh_buffer),
        ("ASSETS", "Cash — Lollar (bank-trapped, real value)", lollar_real_value),
        ("ASSETS", "Inventory — Active Stock (at cost)", inventory_at_cost),
        ("ASSETS", "Security Deposits", SETUP_COSTS["security_deposit"]),
        ("ASSETS", "Store Fit-Out & Equipment (net of depreciation)", round(setup_total * 0.9, 2)),
    ]
    total_assets = round(sum(a[2] for a in assets), 2)
    assets.append(("ASSETS", "TOTAL ASSETS", total_assets))

    # LIABILITIES
    # New store: minimal liabilities. 30-day payable to one local distributor.
    supplier_payable = round(inventory_at_cost * 0.15, 2)  # 15% of inventory on credit terms
    liabilities = [
        ("LIABILITIES", "Accounts Payable — Suppliers (30-day terms)", supplier_payable),
        ("LIABILITIES", "TOTAL LIABILITIES", supplier_payable),
    ]

    # EQUITY
    owner_equity = round(total_assets - supplier_payable, 2)
    equity = [
        ("EQUITY", "Owner's Equity (total capital invested)", owner_equity),
        ("EQUITY", "Retained Earnings", 0.00),
        ("EQUITY", "TOTAL EQUITY", owner_equity),
    ]

    # CHECK
    check = round(total_assets - (supplier_payable + owner_equity), 2)
    balance_check = [
        ("CHECK", "Assets − (Liabilities + Equity)", check),
    ]

    rows = []
    for section_rows in [assets, liabilities, equity, balance_check]:
        for section, line_item, amount in section_rows:
            rows.append({
                "section": section,
                "line_item": line_item,
                "amount_usd": amount,
            })

    return rows, total_assets, supplier_payable, owner_equity, fresh_buffer


def build_opex_assumptions():
    """Output the OpEx assumptions table for transparency."""
    rows = []
    for item, detail in MONTHLY_OPEX.items():
        rows.append({
            "item": item,
            "type": detail["type"],
            "amount_usd": detail["amount_usd"],
            "notes": detail["notes"],
        })
    for item, detail in VARIABLE_COSTS.items():
        rows.append({
            "item": item,
            "type": f"variable_{detail['basis']}",
            "amount_usd": detail["rate"],
            "notes": detail["notes"],
        })
    return rows


def build_cashflow_template(inventory_at_cost):
    """
    Build a 12-month cash flow projection template.

    Uses conservative revenue assumptions based on inventory turnover:
      - Lebanon sportswear store: 3–4× annual inventory turn (realistic)
      - Seasonal weighting: peak in spring/summer/back-to-school
    """
    monthly_fixed = compute_monthly_fixed_opex()

    # Seasonal revenue distribution (% of annual revenue per month)
    # Based on Lebanon retail patterns:
    #   - Jan: post-holiday slow
    #   - Feb-Mar: spring collections arrive
    #   - Apr-May: spring peak
    #   - Jun-Jul: summer sales + tourism
    #   - Aug-Sep: back-to-school (biggest)
    #   - Oct: moderate
    #   - Nov: pre-holiday pickup
    #   - Dec: holiday/gift season
    MONTHLY_REVENUE_SHARE = {
        1: 0.055, 2: 0.065, 3: 0.075, 4: 0.090, 5: 0.095,
        6: 0.100, 7: 0.090, 8: 0.110, 9: 0.100, 10: 0.075,
        11: 0.070, 12: 0.075,
    }

    assert abs(sum(MONTHLY_REVENUE_SHARE.values()) - 1.0) < 0.001, (
        f"MONTHLY_REVENUE_SHARE sums to {sum(MONTHLY_REVENUE_SHARE.values())}, expected 1.0"
    )

    # Annual revenue: 3.5× inventory turn at cost, then convert through margin
    # A 3.5× turn on cost means annual COGS = 3.5 × inventory_at_cost
    annual_cogs = round(inventory_at_cost * 3.5, 2)
    avg_margin = 0.50  # from our blended margin
    annual_revenue = round(annual_cogs / (1 - avg_margin), 2)

    rows = []
    cumulative_cash = 0

    for month in range(1, 13):
        share = MONTHLY_REVENUE_SHARE[month]
        revenue = round(annual_revenue * share, 2)
        cogs = round(revenue * (1 - avg_margin), 2)
        gross_profit = round(revenue - cogs, 2)
        gm_pct = round((gross_profit / revenue) * 100, 1) if revenue > 0 else 0

        # Variable costs
        payment_processing = round(revenue * VARIABLE_COSTS["payment_processing_pct"]["rate"], 2)
        marketing = round(revenue * VARIABLE_COSTS["marketing_pct"]["rate"], 2)
        logistics = round(cogs * VARIABLE_COSTS["logistics_pct_of_cogs"]["rate"], 2)
        shrinkage = round(inventory_at_cost * VARIABLE_COSTS["shrinkage_pct"]["rate"] / 12, 2)
        variable_opex = round(payment_processing + marketing + logistics + shrinkage, 2)
        total_opex = round(monthly_fixed + variable_opex, 2)

        ebitda = round(gross_profit - total_opex, 2)

        # Inventory replenishment: restock ~60% of what was sold (building up slower months)
        restock_cost = round(cogs * 0.60, 2)
        net_cash = round(ebitda - restock_cost, 2)
        cumulative_cash += net_cash

        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        rows.append({
            "month": month,
            "month_name": month_names[month - 1],
            "revenue_usd": revenue,
            "cogs_usd": cogs,
            "gross_profit_usd": gross_profit,
            "gross_margin_pct": gm_pct,
            "fixed_opex_usd": monthly_fixed,
            "variable_opex_usd": variable_opex,
            "total_opex_usd": total_opex,
            "ebitda_usd": ebitda,
            "inventory_restock_usd": restock_cost,
            "net_cash_movement_usd": round(net_cash, 2),
            "cumulative_cash_usd": round(cumulative_cash, 2),
        })

    return rows, annual_revenue, annual_cogs


def build_financial_profile(products, balance_sheet_rows, cashflow_rows,
                             inventory_at_cost, inventory_at_retail,
                             total_assets, supplier_payable, owner_equity,
                             annual_revenue, annual_cogs, fresh_buffer):
    """Build JSON profile summarizing the full financial picture."""
    monthly_fixed = compute_monthly_fixed_opex()
    avg_margin = round(1 - (inventory_at_cost / inventory_at_retail), 4) if inventory_at_retail > 0 else 0.50

    profile = {
        "store_profile": {
            "type": "multi-brand sportswear retailer",
            "location": "Lebanon (Beirut suburb or secondary city)",
            "currency": "fresh USD",
            "fx_rate_lbp_usd": 90000,
            "date_generated": date.today().isoformat(),
        },
        "inventory_summary": {
            "total_skus": len(products),
            "total_units": sum(int(p["initial_stock"]) for p in products),
            "value_at_cost_usd": inventory_at_cost,
            "value_at_retail_usd": inventory_at_retail,
            "blended_margin_pct": round((1 - inventory_at_cost / inventory_at_retail) * 100, 1),
            "brands_carried": len(set(p["brand"] for p in products)),
        },
        "balance_sheet_summary": {
            "total_assets_usd": total_assets,
            "total_liabilities_usd": supplier_payable,
            "total_equity_usd": owner_equity,
            "current_ratio": round(total_assets / supplier_payable, 2) if supplier_payable > 0 else None,
            "inventory_pct_of_assets": round((inventory_at_cost / total_assets) * 100, 1),
        },
        "cashflow_summary": {
            "annual_revenue_projected_usd": annual_revenue,
            "annual_cogs_projected_usd": annual_cogs,
            "monthly_fixed_opex_usd": monthly_fixed,
            "annual_fixed_opex_usd": monthly_fixed * 12,
            "cash_runway_months": round(fresh_buffer / monthly_fixed, 1),
            "breakeven_monthly_revenue_usd": round(monthly_fixed / avg_margin, 2),
        },
        "lebanon_context": {
            "lollar_balance_usd": LOLLAR_BALANCE,
            "lollar_haircut": LOLLAR_HAIRCUT,
            "lollar_real_value_usd": round(LOLLAR_BALANCE * LOLLAR_HAIRCUT, 2),
            "generator_monthly_usd": MONTHLY_OPEX["generator_fuel"]["amount_usd"],
            "grid_hours_per_day": 12,
            "payment_mostly_cash": True,
            "import_lead_time_weeks": "3-8",
            "notes": [
                "All amounts in fresh USD (cash outside banking system).",
                "Lollar is bank-trapped pre-crisis USD, valued at 15¢/$1 for balance sheet purposes.",
                "Generator fuel is a fixed cost because grid electricity covers only ~12h/day.",
                "Payment processing rate is low (1.5%) because ~85% of sales are cash.",
                "Import lead times are 3-8 weeks due to port delays and customs.",
            ],
        },
        "risk_factors": [
            "FX volatility: LBP/USD rate can shift 5-10% in weeks",
            "Import delays: Beirut port congestion adds 1-3 weeks unpredictably",
            "Cash liquidity: banking restrictions limit wire transfers",
            "Fuel cost spikes: generator costs can double during diesel shortages",
            "Seasonal demand concentration: 40% of revenue in Apr-Sep window",
        ],
    }
    return profile


def write_csv(path, rows, fieldnames=None):
    if not rows:
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows → {path}")


def main():
    if not PRODUCTS_CSV.exists():
        print(f"ERROR: {PRODUCTS_CSV} not found. Run build_inventory.py first.")
        sys.exit(1)

    products = load_products()
    inventory_at_cost, inventory_at_retail = compute_inventory_value(products)

    print(f"Loaded {len(products)} products")
    print(f"Inventory at cost:   ${inventory_at_cost:,.2f}")
    print(f"Inventory at retail: ${inventory_at_retail:,.2f}")

    # Balance sheet
    bs_rows, total_assets, supplier_payable, owner_equity, fresh_buffer = \
        build_balance_sheet(inventory_at_cost, inventory_at_retail)
    write_csv(OUT_DIR / "balance_sheet.csv", bs_rows)

    # OpEx assumptions
    opex_rows = build_opex_assumptions()
    write_csv(OUT_DIR / "opex_assumptions.csv", opex_rows)

    # Cashflow template
    cf_rows, annual_revenue, annual_cogs = build_cashflow_template(inventory_at_cost)
    write_csv(OUT_DIR / "cashflow_template.csv", cf_rows)

    # Financial profile JSON
    profile = build_financial_profile(
        products, bs_rows, cf_rows,
        inventory_at_cost, inventory_at_retail,
        total_assets, supplier_payable, owner_equity,
        annual_revenue, annual_cogs, fresh_buffer,
    )
    profile_path = OUT_DIR / "financial_profile.json"
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    print(f"Wrote financial profile → {profile_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("FINANCIAL MODEL SUMMARY — Lebanon Sportswear Store")
    print("=" * 60)
    print(f"Total Assets:            ${total_assets:>12,.2f}")
    print(f"  Inventory (at cost):   ${inventory_at_cost:>12,.2f}")
    print(f"  Fresh Dollar Buffer:   ${fresh_buffer:>12,.2f}")
    print(f"  Lollar (real value):   ${LOLLAR_BALANCE * LOLLAR_HAIRCUT:>12,.2f}")
    print(f"Total Liabilities:       ${supplier_payable:>12,.2f}")
    print(f"Owner's Equity:          ${owner_equity:>12,.2f}")
    check = round(total_assets - supplier_payable - owner_equity, 2)
    print(f"Balance Check (A-L-E):   ${check:>12,.2f}")
    print()
    monthly_fixed = compute_monthly_fixed_opex()
    print(f"Monthly Fixed OpEx:      ${monthly_fixed:>12,.2f}")
    print(f"Annual Fixed OpEx:       ${monthly_fixed * 12:>12,.2f}")
    print(f"Projected Annual Revenue:${annual_revenue:>12,.2f}")
    print(f"Projected Annual COGS:   ${annual_cogs:>12,.2f}")
    print(f"Cash Runway:             {fresh_buffer / monthly_fixed:>10.1f} months")
    print(f"Breakeven (monthly):     ${monthly_fixed / 0.45:>12,.2f}")
    print("=" * 60)
    if check != 0:
        print(f"⚠ BALANCE SHEET DOES NOT BALANCE: diff = ${check}")
    else:
        print("✓ Balance sheet balances perfectly")


if __name__ == "__main__":
    main()
