"""
generate_synthetic.py
=====================
SportEdge Lebanese Adidas Retailer — Synthetic Inventory Dataset Generator

All numbers are grounded in real scraped data:
  - data/outputs/adidas_lb_full_records.csv          (5,082 products)
  - data/outputs/adidas_vs_mikesport_style_code_comparison.csv (577 matched)

Outputs:
  - data/synthetic/products.csv               (~100 SKUs)
  - data/synthetic/inventory.csv              (~100 x 365 = ~36,500 rows)
  - data/synthetic/labels.csv                 (~100 x 52 weeks, labels from week 5+)
  - data/synthetic/management_cashflow.csv    (12 monthly rows)
  - data/synthetic/balance_sheet.csv          (simplified year-end)
  - data/synthetic/opex_assumptions.csv       (fixed + variable cost inputs)
  - data/synthetic/owner_recommendations.txt  (actionable owner guidance)

Simulation period : 2026-01-01 to 2026-12-31
FX rate           : 90,000 LBP / USD (verified from comparison CSV)

Run:
  py -3 data/scripts/generate_synthetic.py
"""

import ast
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parents[2]          # retail-radar-ai/
OUTPUTS = BASE / "data" / "outputs"
SYNTHETIC = BASE / "data" / "synthetic"
SYNTHETIC.mkdir(parents=True, exist_ok=True)

ADIDAS_CSV     = OUTPUTS / "adidas_lb_full_records.csv"
COMPARE_CSV    = OUTPUTS / "adidas_vs_mikesport_style_code_comparison.csv"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RANDOM_SEED     = 42
FX_RATE         = 90_000          # LBP per USD — April 2026 snapshot (verified from comparison CSV)
SIM_START       = date(2026, 1, 1)
SIM_DAYS        = 365
SIM_END         = SIM_START + timedelta(days=SIM_DAYS - 1)

FOOTWEAR_CATS   = {"lifestyle_sneakers", "running_shoes", "training", "football_boots"}

# Category targets: system_category -> (scraped categories list, count)
# Scaled to ~100 SKUs for a small startup retailer.
CATEGORY_MAP = {
    "sportswear": (
        ["Tops", "Joggers & Trousers", "Shorts", "T-Shirts", "Tracksuits",
         "Hoodies", "Sweatshirts", "Leggings", "Sports Bras",
         "Sweatshirts & Hoodies", "T-Shirts & Tops", "Hoodies & Sweatshirts",
         "Jackets & Tracktops"],
        45,
    ),
    "lifestyle_sneakers": (
        ["Originals", "Samba Shoes", "Superstar", "Stan Smith", "Campus", "Gazelle"],
        15,
    ),
    "running_shoes": (
        ["Running", "Supernova", "Ultraboost", "Adizero Collection", "Pureboost",
         "Supernova", "Duramo"],
        12,
    ),
    "training": (
        ["Training", "Shoes", "Basketball", "Tennis", "Skateboarding"],
        10,
    ),
    "accessories": (
        ["Accessories", "Socks", "Bags & Backpacks", "Caps", "Bottles",
         "Gloves", "Sports Balls"],
        10,
    ),
    "football_boots": (
        ["Football", "Predator"],
        5,
    ),
    "kids": (
        ["Boys Clothing", "Girls Clothing", "Boys Shoes", "Girls Shoes"],
        3,
    ),
}

EXCLUDE_CATEGORIES = {
    "Coming Soon", "Excluded", "NEW FOR OUTLET",
    "The Ramadan Shop", "Motorsports", "NEW LINES ADDED - SPRING/SUMMER 2026",
    "Check", "Others", "",
}

# Sport type mapping for products.csv
SPORT_TYPE = {
    "running_shoes":     "running",
    "football_boots":    "football",
    "lifestyle_sneakers":"lifestyle",
    "training":          "training",
    "sportswear":        "training",
    "accessories":       "lifestyle",
    "kids":              "mixed",
}

# Cost ratio bands (low, high) as fraction of original_retail_price_usd
COST_BANDS = {
    "lifestyle_sneakers":         (0.52, 0.58),
    "running_shoes":              (0.50, 0.57),
    "football_boots":             (0.50, 0.58),
    "training_footwear":          (0.50, 0.58),
    "sportswear":                 (0.42, 0.50),
    "accessories":                (0.35, 0.45),
    "kids_footwear":              (0.47, 0.55),
    "kids_apparel":               (0.42, 0.50),
}

# Sell-through horizon ranges (days) per system category
SELL_PERIOD = {
    "sportswear":         (350, 500),
    "training":           (370, 520),
    "running_shoes":      (380, 540),
    "kids":               (380, 540),
    "football_boots":     (400, 560),
    "lifestyle_sneakers": (430, 600),
    "accessories":        (480, 650),
    "dead_stock":         (1100, 1600),
}

# Seasonal multipliers by (system_category, month_1_indexed)
SEASONAL = {
    "running_shoes":      [0.6, 0.6, 1.5, 1.8, 1.6, 1.0, 0.7, 0.8, 1.7, 1.5, 1.1, 0.8],
    "football_boots":     [0.4, 0.4, 0.5, 0.5, 0.6, 0.6, 0.6, 1.8, 2.0, 1.5, 1.3, 0.8],
    "lifestyle_sneakers": [0.8, 0.9, 1.0, 1.4, 1.5, 1.4, 1.3, 1.1, 1.0, 1.0, 1.1, 1.3],
    "sportswear":         [0.9, 0.9, 1.1, 1.2, 1.1, 0.8, 0.7, 0.8, 1.6, 1.1, 1.0, 1.0],
    "accessories":        [1.0, 0.9, 1.0, 1.0, 1.0, 0.9, 0.9, 1.0, 1.2, 1.1, 1.2, 1.3],
    "training":           [0.8, 0.9, 1.0, 1.1, 1.0, 0.9, 0.8, 0.9, 1.4, 1.1, 1.0, 0.9],
    "kids":               [0.8, 0.9, 1.1, 1.2, 1.1, 0.9, 0.8, 1.0, 1.8, 1.1, 1.0, 1.2],
}

# Replenishment modes per category (assigned at product level)
REPLENISHMENT_PROFILE = {
    "sportswear":         ("local_distributor", 7,  21),
    "accessories":        ("local_distributor", 7,  21),
    "training":           ("regional",          21, 45),
    "kids":               ("regional",          21, 45),
    "running_shoes":      ("regional",          21, 45),
    "football_boots":     ("import",            45, 90),
    "lifestyle_sneakers": ("import",            45, 90),
}

TARGET_COVER_DAYS = {
    "local_distributor": (45, 60),
    "regional":          (35, 50),
    "import":            (30, 45),
}

MAX_RESTOCKS = {
    "local_distributor": (4, 8),
    "regional":          (3, 5),
    "import":            (2, 3),
    "never":             (0, 0),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def seasonal_mult(system_category: str, d: date) -> float:
    table = SEASONAL.get(system_category, SEASONAL["accessories"])
    return table[d.month - 1]


def event_mult(system_category: str, d: date) -> float:
    m, day = d.month, d.day
    mult = 1.0
    # Black Friday
    if m == 11 and 25 <= day <= 29:
        mult = max(mult, random.uniform(2.0, 3.0))
    # January Sale
    if m == 1 and day <= 10:
        mult = max(mult, random.uniform(1.5, 2.0))
    # Ramadan (Mar 20 – Apr 19)
    if (m == 3 and day >= 20) or (m == 4 and day <= 19):
        if system_category == "lifestyle_sneakers":
            mult = max(mult, random.uniform(1.2, 1.4))
        elif system_category == "sportswear":
            mult = max(mult, random.uniform(1.1, 1.2))
    # Back to School (Sep 1–10)
    if m == 9 and day <= 10:
        if system_category == "sportswear":
            mult = max(mult, random.uniform(1.5, 1.8))
        elif system_category == "kids":
            mult = max(mult, random.uniform(1.6, 2.0))
        elif system_category == "training":
            mult = max(mult, random.uniform(1.3, 1.5))
    return mult


def weekend_mult(d: date) -> float:
    return random.uniform(1.10, 1.20) if d.weekday() >= 5 else 1.0


def noise() -> float:
    return random.uniform(0.85, 1.15)


def parse_sizes(s) -> list:
    try:
        return ast.literal_eval(str(s))
    except Exception:
        return []


def cost_band_key(system_category: str, product_name: str) -> str:
    name_lower = str(product_name).lower()
    if system_category == "training":
        if any(w in name_lower for w in ["shoe", "sneaker", "boot", "trainer"]):
            return "training_footwear"
        return "sportswear"
    if system_category == "kids":
        if any(w in name_lower for w in ["shoe", "sneaker", "boot", "trainer", "slides"]):
            return "kids_footwear"
        return "kids_apparel"
    return system_category


def assign_collection_type(system_category: str, product_name: str, is_on_sale: bool) -> str:
    name = str(product_name).lower()
    if any(w in name for w in ["collab", "special", "limited"]):
        return "collab"
    if is_on_sale:
        return "seasonal"
    if system_category in ("accessories", "sportswear"):
        return "core"
    return "seasonal"


# ---------------------------------------------------------------------------
# SECTION 1 — Load and sample ~100 products
# ---------------------------------------------------------------------------

def load_products() -> pd.DataFrame:
    print("[1/9] Loading product catalog …")
    raw = pd.read_csv(ADIDAS_CSV)

    # Filter
    raw = raw[raw["data_valid"] == True].copy()
    raw = raw[~raw["category"].isin(EXCLUDE_CATEGORIES)].copy()
    raw["style_code"] = raw["style_code"].astype(str).str.strip()
    raw = raw.drop_duplicates(subset="style_code", keep="first").reset_index(drop=True)

    records = []
    for sys_cat, (scraped_cats, target_n) in CATEGORY_MAP.items():
        pool = raw[raw["category"].isin(scraped_cats)].copy()
        if len(pool) < target_n:
            # Fail loudly — the real source data must support the designed sample size.
            # Silently under-filling produces misleading downstream distributions.
            raise ValueError(
                f"Category '{sys_cat}' has only {len(pool)} eligible products "
                f"but requires {target_n}. Check ADIDAS_CSV filters or CATEGORY_MAP."
            )
        sample = pool.sample(n=target_n, random_state=RANDOM_SEED).copy()
        sample["system_category"] = sys_cat
        records.append(sample)

    df = pd.concat(records, ignore_index=True)

    # Core fields
    df["sku_id"]             = "SKU-" + df["style_code"]
    df["num_sizes"]          = df["sizes_available"].apply(lambda x: len(parse_sizes(x)))
    df["retail_price_lbp"]   = df["competitor_price"]
    df["retail_price_usd"]   = (df["retail_price_lbp"] / FX_RATE).round(2)
    df["fx_rate_used"]       = FX_RATE
    df["fx_date"]            = "2026-04-05/06 snapshot"
    df["is_currently_on_sale"]  = df["is_on_sale"]
    df["current_discount_pct"]  = df["discount_pct"].fillna(0.0)

    # Reconstruct original pre-discount price
    df["original_retail_price_usd"] = df.apply(
        lambda r: (r["retail_price_usd"] / (1 - r["current_discount_pct"] / 100))
        if (r["is_currently_on_sale"] and r["current_discount_pct"] > 0)
        else r["retail_price_usd"],
        axis=1,
    ).round(2)
    df["original_retail_price_lbp"] = (df["original_retail_price_usd"] * FX_RATE).round(0)

    df["sport_type"]     = df["system_category"].map(SPORT_TYPE)
    df["collection_type"] = df.apply(
        lambda r: assign_collection_type(r["system_category"], r["product_name"], r["is_currently_on_sale"]),
        axis=1,
    )
    df["gender_target"] = df["gender_target"].fillna("unisex")

    print(f"    Loaded {len(df)} products.")
    _check_category_counts(df)
    return df


def _check_category_counts(df: pd.DataFrame):
    counts = df["system_category"].value_counts()
    for cat, (_, target) in CATEGORY_MAP.items():
        actual = counts.get(cat, 0)
        status = "OK" if actual == target else f"WARN (want {target})"
        print(f"    {cat:25s} {actual:3d}  {status}")


# ---------------------------------------------------------------------------
# SECTION 2 — Cost price
# ---------------------------------------------------------------------------

def assign_cost(df: pd.DataFrame) -> pd.DataFrame:
    print("[2/9] Assigning cost prices …")
    cost_ratios, gross_margins = [], []

    for _, row in df.iterrows():
        band_key  = cost_band_key(row["system_category"], row["product_name"])
        lo, hi    = COST_BANDS[band_key]

        # Bias toward upper half (lower margin) for on-sale items
        if row["is_currently_on_sale"]:
            lo = (lo + hi) / 2

        ratio = random.uniform(lo, hi)
        cost  = round(row["original_retail_price_usd"] * ratio, 2)
        gm    = round((row["original_retail_price_usd"] - cost) / row["original_retail_price_usd"], 4)

        cost_ratios.append(ratio)
        gross_margins.append(gm)

    df["cost_price_usd"]  = [round(r["original_retail_price_usd"] * cr, 2)
                              for r, cr in zip(df.to_dict("records"), cost_ratios)]
    df["gross_margin_pct"] = gross_margins
    return df


# ---------------------------------------------------------------------------
# SECTION 3 — Initial stock
# ---------------------------------------------------------------------------

def assign_stock(df: pd.DataFrame) -> pd.DataFrame:
    print("[3/9] Assigning initial stock …")
    stocks, dead_flags, sell_mults, never_restocks = [], [], [], []

    for _, row in df.iterrows():
        n   = row["num_sizes"]
        cat = row["system_category"]

        # Dead stock override — only the most extreme cases
        if row["current_discount_pct"] >= 50 and n <= 1:
            stocks.append(random.randint(2, 8))
            dead_flags.append(True)
            sell_mults.append(random.uniform(0.03, 0.10))
            never_restocks.append(True)
            continue

        dead_flags.append(False)
        sell_mults.append(1.0)
        never_restocks.append(False)

        # Calibrated stock depths (tuned with 350–600 day sell periods).
        # ~100 SKUs × these depths → ~$200K opening inventory at cost.
        if cat in FOOTWEAR_CATS:
            if   n >= 10: stocks.append(n * random.randint(8, 16))
            elif n >= 7:  stocks.append(n * random.randint(6, 12))
            elif n >= 4:  stocks.append(n * random.randint(4, 10))
            elif n >= 2:  stocks.append(n * random.randint(3, 8))
            else:         stocks.append(random.randint(4, 12))
        else:
            if   n >= 10: stocks.append(n * random.randint(5, 10))
            elif n >= 7:  stocks.append(n * random.randint(4, 8))
            elif n >= 4:  stocks.append(n * random.randint(3, 7))
            elif n >= 2:  stocks.append(n * random.randint(2, 6))
            else:         stocks.append(random.randint(4, 15))

    df["initial_stock"]          = stocks
    df["is_dead_stock_candidate"] = dead_flags
    df["sell_rate_multiplier"]   = sell_mults
    df["never_restocks"]         = never_restocks
    return df


# ---------------------------------------------------------------------------
# SECTION 4 — Competitive pressure
# ---------------------------------------------------------------------------

def assign_competitive(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign real competitor price gaps where data exists (577 matches).
    For the ~89% of products with no match, simulate a gap drawn from the
    real observed distribution:
      40.38% premium  (gap between +0.03 and +0.25)
      48.18% neutral  (gap between -0.03 and +0.03)
      11.44% value    (gap between -0.20 and -0.03)
    """
    print("[4/9] Assigning competitive pressure …")
    comp = pd.read_csv(COMPARE_CSV, usecols=[
        "style_code",
        "mikesport_current_price_min_usd",
        "adidas_current_price_min_usd",
        "comparison_current_price_diff_usd",
        "comparison_current_price_diff_pct_vs_adidas_usd",
    ])
    comp["style_code"] = comp["style_code"].astype(str).str.strip()
    matched = comp.set_index("style_code")

    gaps_usd, gaps_pct, signals, is_real = [], [], [], []

    for _, row in df.iterrows():
        sc = str(row["style_code"]).strip()
        if sc in matched.index:
            mike_price = matched.loc[sc, "mikesport_current_price_min_usd"]
            adidas_price = row["retail_price_usd"]
            if pd.notna(mike_price) and mike_price > 0:
                gap_usd = round(adidas_price - mike_price, 2)
                gap_pct = round(gap_usd / mike_price, 4)
                if gap_pct > 0.03:
                    sig = "premium"
                elif gap_pct < -0.03:
                    sig = "value"
                else:
                    sig = "neutral"
                gaps_usd.append(gap_usd)
                gaps_pct.append(gap_pct)
                signals.append(sig)
                is_real.append(True)
                continue

        # Simulate gap from real observed distribution
        r = random.random()
        if r < 0.4038:          # 40.38% premium
            gap_pct = round(random.uniform(0.03, 0.20), 4)
            sig = "premium"
        elif r < 0.4038 + 0.4818:  # 48.18% neutral
            gap_pct = round(random.uniform(-0.03, 0.03), 4)
            sig = "neutral"
        else:                   # 11.44% value
            gap_pct = round(random.uniform(-0.20, -0.03), 4)
            sig = "value"
        gap_usd = round(gap_pct * row["retail_price_usd"], 2)
        gaps_usd.append(gap_usd)
        gaps_pct.append(gap_pct)
        signals.append(sig)
        is_real.append(False)

    df["price_gap_usd"]        = gaps_usd
    df["price_gap_pct"]        = gaps_pct
    df["competitor_signal"]    = signals
    df["competitor_data_real"] = is_real
    return df


# ---------------------------------------------------------------------------
# SECTION 5+6 — Replenishment setup, then 365-day simulation
# ---------------------------------------------------------------------------

def assign_replenishment(df: pd.DataFrame) -> pd.DataFrame:
    print("[5/9] Assigning replenishment profiles …")
    modes, lead_lows, lead_highs, lead_times, sell_periods = [], [], [], [], []

    # ~5% random permanent stockouts among non-dead-stock
    n_products = len(df)
    perm_stockout_indices = set(
        random.sample(
            list(df[~df["is_dead_stock_candidate"]].index),
            k=max(1, int(n_products * random.uniform(0.03, 0.08))),
        )
    )

    for idx, row in df.iterrows():
        cat = row["system_category"]
        if row["never_restocks"]:
            modes.append("never")
            lead_lows.append(0); lead_highs.append(0); lead_times.append(0)
        else:
            mode, lo, hi = REPLENISHMENT_PROFILE[cat]
            lt = random.randint(lo, hi)
            modes.append(mode)
            lead_lows.append(lo); lead_highs.append(hi); lead_times.append(lt)

        if row["is_dead_stock_candidate"]:
            sp = random.randint(*SELL_PERIOD["dead_stock"])
        else:
            sp = random.randint(*SELL_PERIOD[cat])
        sell_periods.append(sp)

    df["replenishment_mode"] = modes
    df["lead_time_lo"]       = lead_lows
    df["lead_time_hi"]       = lead_highs
    df["lead_time_days"]     = lead_times
    df["sell_period_days"]   = sell_periods
    df["_perm_stockout"]     = [i in perm_stockout_indices for i in df.index]
    return df


def simulate_inventory(df: pd.DataFrame):
    print("[6/9] Simulating 365-day inventory …")

    inv_rows   = []
    all_dates  = [SIM_START + timedelta(days=i) for i in range(SIM_DAYS)]

    products = df.to_dict("records")

    for prod in products:
        sku            = prod["sku_id"]
        cat            = prod["system_category"]
        init_stock     = int(prod["initial_stock"])
        base_rate      = init_stock / prod["sell_period_days"]
        sell_mult      = prod["sell_rate_multiplier"]
        lead_lo        = prod["lead_time_lo"]
        lead_hi        = prod["lead_time_hi"]
        mode           = prod["replenishment_mode"]
        never          = prod["never_restocks"]
        perm_so        = prod["_perm_stockout"]
        max_restocks   = random.randint(*MAX_RESTOCKS.get(mode, (0, 0)))
        cover_lo, cover_hi = TARGET_COVER_DAYS.get(mode, (0, 0))
        cost_usd       = float(prod["cost_price_usd"])
        retail_usd     = float(prod["retail_price_usd"])

        stock          = init_stock
        cumul_sold     = 0
        cumul_restock  = 0
        restock_count  = 0
        permanent_out  = False

        # Pending restock: (due_day_index, qty)
        pending_restocks = []

        # Rolling demand window (last 28 days)
        demand_window  = []

        for day_i, d in enumerate(all_dates):
            # Record opening stock BEFORE receipts arrive.
            # Selling uses this pre-receipt value so same-day arrivals do not
            # inflate same-day sales — operationally, goods received during the
            # day are only available to sell from the following day onward.
            stock_start = stock

            # Accumulate any restocks due today (they count toward end-of-day
            # stock but are not available for today's selling).
            restock_today = 0
            still_pending = []
            for due, qty in pending_restocks:
                if day_i >= due:
                    restock_today += qty
                    cumul_restock += qty
                    restock_count += 1
                else:
                    still_pending.append((due, qty))
            pending_restocks = still_pending

            # Daily sales — drawn against pre-receipt opening stock only
            s_mult = seasonal_mult(cat, d)
            e_mult = event_mult(cat, d)
            w_mult = weekend_mult(d)
            n_mult = noise()

            # Poisson process avoids systematic rounding-to-zero for low base rates
            lam        = max(0.0, base_rate * sell_mult * s_mult * e_mult * w_mult * n_mult)
            daily_sold = min(stock_start, int(np.random.poisson(lam)))
            # End-of-day stock: open stock minus sales, then add today's receipts
            stock      = stock_start - daily_sold + restock_today
            cumul_sold += daily_sold

            # Rolling demand (update BEFORE reorder check)
            demand_window.append(daily_sold)
            if len(demand_window) > 28:
                demand_window.pop(0)

            # Permanent stockout check
            if stock == 0 and perm_so and not permanent_out:
                permanent_out = True

            is_stockout = (stock == 0)

            # Reorder logic (ROP formula, only from day 28 onward)
            restock_triggered = False
            reorder_point     = 0.0
            safety_stock_val  = 0.0

            if (
                len(demand_window) >= 14
                and not never
                and not permanent_out
                and mode != "never"
                and restock_count < max_restocks
                and not pending_restocks  # one pending order at a time
            ):
                avg_demand = float(np.mean(demand_window))
                if avg_demand > 0:
                    # Safety days
                    if cat in ("sportswear", "accessories") and prod["collection_type"] == "core":
                        safety_days = random.randint(7, 14)
                    else:
                        safety_days = random.randint(14, 21)

                    safety_stock_val = avg_demand * safety_days
                    lt = random.randint(lead_lo, lead_hi) if lead_hi > 0 else 0
                    reorder_point = (avg_demand * lt) + safety_stock_val

                    if stock <= reorder_point:
                        cover = random.randint(cover_lo, cover_hi)
                        target_units = avg_demand * cover
                        qty = max(0, round(target_units - stock))
                        if qty > 0:
                            pending_restocks.append((day_i + lt, qty))
                            restock_triggered = True

            # Days of supply — use 28-day rolling average (smooths seasonal dips)
            avg_28d = float(np.mean(demand_window)) if demand_window else base_rate
            avg_28d = max(avg_28d, base_rate * 0.05)   # floor at 5% of base rate
            dos     = min(stock / avg_28d, 9999.0)      # cap high to differentiate dead stock

            # Sell-through rate
            total_available = cumul_sold + stock
            str_rate = (cumul_sold / total_available) if total_available > 0 else 0.0

            # Velocity ratio (only meaningful after 14 days)
            if day_i >= 14 and len(demand_window) >= 14:
                recent   = float(np.mean(demand_window[-7:]))
                baseline = float(np.mean(demand_window[:-7])) if len(demand_window) > 7 else recent
                vel_ratio = (recent / baseline) if baseline > 0 else 1.0
            else:
                vel_ratio = 1.0

            inv_rows.append({
                "sku_id":             sku,
                "date":               d.isoformat(),
                "month":              d.month,
                "system_category":    cat,
                "stock_start_of_day": stock_start,
                "units_sold":         daily_sold,
                "restock_units":      restock_today,
                "stock_end_of_day":   stock,
                "revenue_usd":        round(daily_sold * retail_usd, 4),
                "cogs_usd":           round(daily_sold * cost_usd, 4),
                "restock_cost_usd":   round(restock_today * cost_usd, 4),
                "days_of_supply":     round(min(dos, 999.0), 2),
                "sell_through_rate":  round(str_rate, 4),
                "velocity_ratio":     round(vel_ratio, 4),
                "is_stockout":        is_stockout,
                "restock_triggered":  restock_triggered,
                "cumulative_units_sold":   cumul_sold,
                "cumulative_restock_units": cumul_restock,
                "reorder_point":      round(reorder_point, 2),
                "safety_stock":       round(safety_stock_val, 2),
                "seasonal_mult":      round(s_mult, 3),
            })

    inv_df = pd.DataFrame(inv_rows)
    print(f"    Generated {len(inv_df):,} inventory rows.")
    return inv_df


# ---------------------------------------------------------------------------
# SECTION 7 — Weekly labels
# ---------------------------------------------------------------------------

def assign_labels(df: pd.DataFrame, inv_df: pd.DataFrame) -> pd.DataFrame:
    print("[7/9] Assigning weekly labels …")
    label_rows = []

    for prod in df.to_dict("records"):
        sku       = prod["sku_id"]
        cat       = prod["system_category"]
        gm        = prod["gross_margin_pct"]
        pgap      = prod["price_gap_pct"]
        is_dead   = prod["is_dead_stock_candidate"]
        sku_inv   = inv_df[inv_df["sku_id"] == sku].sort_values("date").reset_index(drop=True)

        for week_num in range(1, 53):
            # Week slice (day indices 0-based)
            w_start_i = (week_num - 1) * 7
            w_end_i   = min(w_start_i + 7, SIM_DAYS)
            week_rows = sku_inv.iloc[w_start_i:w_end_i]
            if week_rows.empty:
                continue

            week_start_date = (SIM_START + timedelta(days=w_start_i)).isoformat()

            # Cold-start: weeks 1-4 get no label
            if week_num <= 4:
                label_rows.append({
                    "sku_id":           sku,
                    "week_start_date":  week_start_date,
                    "week_number":      week_num,
                    "label":            None,
                    "days_of_supply":   None,
                    "sell_through_rate":None,
                    "velocity_ratio":   1.0,
                    "price_gap_pct":    pgap,
                    "gross_margin_pct": gm,
                    "seasonal_mult":    None,
                    "rule_triggered":   "cold_start",
                })
                continue

            # Aggregates — use stored values from inventory simulation
            # days_of_supply already uses 28-day rolling avg with base_rate floor
            dos      = float(week_rows["days_of_supply"].iloc[-1])
            str_rate = float(week_rows["sell_through_rate"].iloc[-1])
            vel      = float(week_rows["velocity_ratio"].mean())
            s_mult   = float(week_rows["seasonal_mult"].mean())

            # Label rules — first match wins
            # CLEAR: dead stock with extreme oversupply
            clear_score = (is_dead and dos > 950 and s_mult < 1.12) or \
                          (dos > 1300 and str_rate < 0.05)
            if clear_score:
                label   = "CLEAR"
                trigger = "rule_clear"
            # MARKDOWN: slow-moving inventory at risk of becoming dead stock
            elif dos > 40 and vel < 0.80 and (pgap > -0.01 or str_rate < 0.40):
                label   = "MARKDOWN"
                trigger = "rule_markdown"
            # PROMOTE: peak demand window + margin + enough stock
            elif s_mult >= 1.12 and dos > 12 and gm > 0.28:
                label   = "PROMOTE"
                trigger = "rule_promote"
            else:
                label   = "HOLD"
                trigger = "rule_hold"

            label_rows.append({
                "sku_id":           sku,
                "week_start_date":  week_start_date,
                "week_number":      week_num,
                "label":            label,
                "days_of_supply":   round(dos, 2),
                "sell_through_rate":round(str_rate, 4),
                "velocity_ratio":   round(vel, 4),
                "price_gap_pct":    pgap,
                "gross_margin_pct": gm,
                "seasonal_mult":    round(s_mult, 3),
                "rule_triggered":   trigger,
            })

    labels_df = pd.DataFrame(label_rows)
    print(f"    Generated {len(labels_df):,} label rows.")
    return labels_df


# ---------------------------------------------------------------------------
# SECTION 8 — Save outputs
# ---------------------------------------------------------------------------

PRODUCT_COLS = [
    "style_code", "sku_id", "product_name", "colorway", "system_category",
    "sport_type", "gender_target", "retail_price_lbp", "retail_price_usd",
    "original_retail_price_lbp", "original_retail_price_usd", "cost_price_usd",
    "gross_margin_pct", "num_sizes", "initial_stock", "is_currently_on_sale",
    "current_discount_pct", "competitor_signal", "price_gap_pct", "price_gap_usd",
    "is_dead_stock_candidate", "replenishment_mode", "lead_time_days",
    "sell_period_days", "collection_type", "fx_rate_used", "fx_date",
]

INV_COLS = [
    "sku_id", "date", "month", "system_category", "stock_start_of_day",
    "units_sold", "restock_units", "stock_end_of_day", "revenue_usd",
    "cogs_usd", "restock_cost_usd", "days_of_supply", "sell_through_rate",
    "velocity_ratio", "is_stockout", "restock_triggered",
    "cumulative_units_sold", "cumulative_restock_units", "reorder_point",
    "safety_stock", "seasonal_mult",
]

LABEL_COLS = [
    "sku_id", "week_start_date", "week_number", "label", "days_of_supply",
    "sell_through_rate", "velocity_ratio", "price_gap_pct", "gross_margin_pct",
    "seasonal_mult", "rule_triggered",
]


def save_outputs(df, inv_df, labels_df, cashflow_df, balance_df, opex_df, rec_text):
    print("[8/9] Saving output files …")
    df[PRODUCT_COLS].to_csv(SYNTHETIC / "products.csv", index=False)
    inv_df[INV_COLS].to_csv(SYNTHETIC / "inventory.csv", index=False)
    labels_df[LABEL_COLS].to_csv(SYNTHETIC / "labels.csv", index=False)
    cashflow_df.to_csv(SYNTHETIC / "management_cashflow.csv", index=False)
    balance_df.to_csv(SYNTHETIC / "balance_sheet.csv", index=False)
    opex_df.to_csv(SYNTHETIC / "opex_assumptions.csv", index=False)
    with open(SYNTHETIC / "owner_recommendations.txt", "w", encoding="utf-8") as f:
        f.write(rec_text)
    print(f"    products.csv               : {len(df)} rows")
    print(f"    inventory.csv              : {len(inv_df):,} rows")
    print(f"    labels.csv                 : {len(labels_df):,} rows")
    print(f"    management_cashflow.csv    : {len(cashflow_df)} rows")
    print(f"    balance_sheet.csv          : {len(balance_df)} rows")
    print(f"    opex_assumptions.csv       : {len(opex_df)} rows")
    print(f"    owner_recommendations.txt  : written")


# ---------------------------------------------------------------------------
# SECTION 9 — Validation
# ---------------------------------------------------------------------------

def validate(df, inv_df, labels_df, cashflow_df, balance_df):
    print("[9/9] Running validation checks …")
    errors = []

    # 1. Label distribution (excluding cold-start nulls)
    real_labels = labels_df[labels_df["label"].notna()]["label"]
    dist = real_labels.value_counts(normalize=True)
    for lbl, lo, hi in [("HOLD", 0.42, 0.48), ("MARKDOWN", 0.22, 0.28),
                         ("PROMOTE", 0.17, 0.23), ("CLEAR", 0.07, 0.13)]:
        v = dist.get(lbl, 0)
        if not (lo <= v <= hi):
            errors.append(f"  FAIL Label {lbl}: {v:.1%} not in [{lo:.0%}, {hi:.0%}]")

    # 2. Cold-start weeks 1–4 must have null labels
    cold = labels_df[labels_df["week_number"] <= 4]["label"]
    if cold.notna().any():
        errors.append("  FAIL Cold-start weeks 1–4 have non-null labels")

    # 3. No negative stock
    neg = (inv_df["stock_end_of_day"] < 0).sum()
    if neg > 0:
        errors.append(f"  FAIL {neg} rows have negative stock_end_of_day")

    # 4. No overselling
    totals = inv_df.groupby("sku_id").agg(
        total_sold=("units_sold", "sum"),
        total_restock=("cumulative_restock_units", "max"),
    ).reset_index()
    totals = totals.merge(df[["sku_id", "initial_stock"]], on="sku_id")
    over = totals[totals["total_sold"] > totals["initial_stock"] + totals["total_restock"]]
    if not over.empty:
        errors.append(f"  FAIL {len(over)} SKUs oversold beyond initial + restock")

    # 5. Dead stock must end year with stock > 0
    dead_skus = df[df["is_dead_stock_candidate"]]["sku_id"].tolist()
    last_day  = inv_df[inv_df["date"] == SIM_END.isoformat()]
    dead_end  = last_day[last_day["sku_id"].isin(dead_skus)]["stock_end_of_day"]
    if (dead_end == 0).any():
        n = (dead_end == 0).sum()
        errors.append(f"  FAIL {n} dead-stock SKUs sold out completely (should retain stock)")

    # 6. Stockout realism
    non_dead = df[~df["is_dead_stock_candidate"]]["sku_id"].tolist()
    so_skus  = inv_df[(inv_df["sku_id"].isin(non_dead)) & (inv_df["is_stockout"])]["sku_id"].nunique()
    pct_so   = so_skus / max(len(non_dead), 1)
    if not (0.03 <= pct_so <= 0.20):
        errors.append(f"  WARN Stockout coverage {pct_so:.1%} outside [3%, 20%]")

    # 7. Restock realism
    restocked = inv_df[(inv_df["sku_id"].isin(non_dead)) & (inv_df["restock_triggered"])]["sku_id"].nunique()
    pct_re    = restocked / max(len(non_dead), 1)
    if not (0.40 <= pct_re <= 0.95):
        errors.append(f"  WARN Restock coverage {pct_re:.1%} outside [40%, 95%]")

    # 8. Gross margin realism
    gm_bad = df[(df["gross_margin_pct"] < 0.38) | (df["gross_margin_pct"] > 0.70)]
    if not gm_bad.empty:
        errors.append(f"  FAIL {len(gm_bad)} SKUs have gross margin outside [38%, 70%]")
    blended = df["gross_margin_pct"].mean()
    if not (0.45 <= blended <= 0.60):
        errors.append(f"  WARN Blended gross margin {blended:.1%} outside [45%, 60%]")

    # 9. Cost always below original retail
    below_cost = df[df["cost_price_usd"] >= df["original_retail_price_usd"]]
    if not below_cost.empty:
        errors.append(f"  FAIL {len(below_cost)} SKUs have cost >= original retail price")

    # 10. Category counts
    counts = df["system_category"].value_counts()
    for cat, (_, target) in CATEGORY_MAP.items():
        actual = counts.get(cat, 0)
        if actual != target:
            errors.append(f"  WARN Category {cat}: {actual} products, expected {target}")

    # 11. Balance sheet check
    bs_check_row = balance_df[balance_df["line_item"] == "Assets minus (Liabilities + Equity)"]
    if not bs_check_row.empty:
        bs_delta = abs(float(bs_check_row["amount_usd"].iloc[0]))
        if bs_delta > 1.0:
            errors.append(f"  FAIL Balance sheet delta = ${bs_delta:.2f}")

    # 12. Positive monthly revenue
    if (cashflow_df["revenue_usd"] <= 0).any():
        errors.append("  FAIL Some months have zero or negative revenue")

    # Print results
    print()
    if errors:
        for e in errors:
            print(e)
        print(f"\n  {len(errors)} issue(s) found. Review above.")
    else:
        print("  All validation checks PASSED.")

    # Summary stats
    print(f"\n  --- Summary ---")
    print(f"  Label distribution (real labels only):")
    for lbl in ["HOLD", "MARKDOWN", "PROMOTE", "CLEAR"]:
        print(f"    {lbl:10s} {dist.get(lbl, 0):.1%}")
    print(f"  Blended gross margin : {blended:.1%}")
    opening_inv_value = (df["initial_stock"] * df["cost_price_usd"]).sum()
    print(f"  Opening inv value    : ${opening_inv_value:,.0f} (at cost)")
    ending_stock = last_day.set_index("sku_id")["stock_end_of_day"]
    ending_inv_value = sum(
        ending_stock.get(r["sku_id"], 0) * r["cost_price_usd"]
        for _, r in df.iterrows()
    )
    print(f"  Ending inv value     : ${ending_inv_value:,.0f} (at cost)")
    print(f"  Stockout coverage    : {pct_so:.1%} of non-dead SKUs")
    print(f"  Restock coverage     : {pct_re:.1%} of non-dead SKUs")

    # Financial highlights
    annual_rev  = float(cashflow_df["revenue_usd"].sum())
    annual_gp   = float(cashflow_df["gross_profit_usd"].sum())
    annual_opex = float(cashflow_df["total_opex_usd"].sum())
    annual_ebitda = float(cashflow_df["ebitda_like_usd"].sum())
    # Closing cash from balance sheet (correct cash-basis, not the P&L-hybrid cumulative)
    bs_cash_row = balance_df[balance_df["line_item"] == "Cash & Cash Equivalents"]
    closing_cash = float(bs_cash_row["amount_usd"].iloc[0]) if not bs_cash_row.empty else 0.0
    print(f"\n  --- Financial Highlights (Full Year 2026) ---")
    print(f"  Annual Revenue       : ${annual_rev:,.0f}")
    print(f"  Annual Gross Profit  : ${annual_gp:,.0f}")
    print(f"  Annual Total OpEx    : ${annual_opex:,.0f}")
    print(f"  Annual EBITDA-like   : ${annual_ebitda:,.0f}")
    print(f"  Closing Cash         : ${closing_cash:,.0f}")
    print(f"  Year-End Inv (cost)  : ${ending_inv_value:,.0f}")


# ---------------------------------------------------------------------------
# SECTION 10 — Operating cost layer
# ---------------------------------------------------------------------------

def build_opex():
    print("  [10] Building OpEx assumptions …")
    # Startup-scale monthly costs: small corner shop, owner-operated in Lebanon
    monthly_fixed = {
        "rent_usd":      round(random.uniform(700, 1_300), 2),
        "salaries_usd":  round(random.uniform(800, 1_500), 2),
        "utilities_usd": round(random.uniform(100, 220), 2),
        "misc_opex_usd": round(random.uniform(60, 150), 2),
    }
    variable_rates = {
        "payment_processing_pct": round(random.uniform(0.015, 0.025), 4),
        "marketing_pct":          round(random.uniform(0.020, 0.040), 4),
        "logistics_pct_of_cogs":  round(random.uniform(0.010, 0.020), 4),
    }
    rows = []
    for k, v in monthly_fixed.items():
        rows.append({"item": k, "type": "fixed_monthly_usd", "value": v})
    for k, v in variable_rates.items():
        rows.append({"item": k, "type": "variable_rate", "value": v})
    return pd.DataFrame(rows), monthly_fixed, variable_rates


# ---------------------------------------------------------------------------
# SECTION 11 — Management cash-flow summary
# ---------------------------------------------------------------------------

def build_cashflow(inv_df, monthly_fixed, variable_rates):
    print("  [11] Building management cash-flow summary …")
    monthly_agg = (
        inv_df.groupby("month")
        .agg(
            units_sold=("units_sold", "sum"),
            revenue_usd=("revenue_usd", "sum"),
            cogs_usd=("cogs_usd", "sum"),
            inventory_purchase_usd=("restock_cost_usd", "sum"),
        )
        .reset_index()
    )
    monthly_agg["gross_profit_usd"] = monthly_agg["revenue_usd"] - monthly_agg["cogs_usd"]
    monthly_agg["gross_margin_pct"] = (
        monthly_agg["gross_profit_usd"] / monthly_agg["revenue_usd"].replace(0, np.nan)
    )

    # Opening cash reserve (working capital alongside inventory investment)
    opening_cash = round(random.uniform(25_000, 45_000), 2)
    cumulative_cash = opening_cash
    rows = []

    for _, mrow in monthly_agg.iterrows():
        m   = int(mrow["month"])
        rev = float(mrow["revenue_usd"])
        cogs = float(mrow["cogs_usd"])
        gp  = float(mrow["gross_profit_usd"])

        total_fixed   = sum(monthly_fixed.values())
        pay_fee       = rev * variable_rates["payment_processing_pct"]
        marketing     = rev * variable_rates["marketing_pct"]
        logistics     = cogs * variable_rates["logistics_pct_of_cogs"]
        total_variable = pay_fee + marketing + logistics
        total_opex    = total_fixed + total_variable

        ebitda_like       = gp - total_opex
        inv_purchase      = float(mrow["inventory_purchase_usd"])
        net_cash_movement = ebitda_like - inv_purchase
        cumulative_cash  += net_cash_movement

        rows.append({
            "month":                  m,
            "month_name":             date(2026, m, 1).strftime("%B"),
            "units_sold":             int(mrow["units_sold"]),
            "revenue_usd":           round(rev, 2),
            "cogs_usd":             round(cogs, 2),
            "gross_profit_usd":     round(gp, 2),
            "gross_margin_pct":     round(float(mrow["gross_margin_pct"])
                                          if pd.notna(mrow["gross_margin_pct"]) else 0, 4),
            "fixed_opex_usd":       round(total_fixed, 2),
            "variable_opex_usd":    round(total_variable, 2),
            "total_opex_usd":       round(total_opex, 2),
            "ebitda_like_usd":      round(ebitda_like, 2),
            "inventory_purchase_usd": round(inv_purchase, 2),
            "net_cash_movement_usd": round(net_cash_movement, 2),
            "cumulative_cash_usd":  round(cumulative_cash, 2),
        })

    return pd.DataFrame(rows), opening_cash


# ---------------------------------------------------------------------------
# SECTION 12 — Year-end balance sheet (simplified)
# ---------------------------------------------------------------------------

def build_balance_sheet(df, inv_df, cashflow_df, opening_cash):
    print("  [12] Building year-end balance sheet …")
    last_day = inv_df[inv_df["date"] == SIM_END.isoformat()]

    inv_value_usd = 0.0
    dead_value    = 0.0
    for _, prod in df.iterrows():
        sku   = prod["sku_id"]
        cost  = float(prod["cost_price_usd"])
        ye    = last_day[last_day["sku_id"] == sku]
        units = int(ye.iloc[0]["stock_end_of_day"]) if not ye.empty else 0
        val   = units * cost
        inv_value_usd += val
        if prod["is_dead_stock_candidate"]:
            dead_value += val

    active_inv_value = inv_value_usd - dead_value

    # Cash position: opening cash + revenue - opex - inventory purchases
    # (COGS is NOT a cash outflow — it reduces the inventory asset, not cash)
    total_revenue   = float(cashflow_df["revenue_usd"].sum())
    total_opex      = float(cashflow_df["total_opex_usd"].sum())
    total_inv_purch = float(cashflow_df["inventory_purchase_usd"].sum())
    closing_cash    = opening_cash + total_revenue - total_opex - total_inv_purch

    # Accounts receivable (small — mostly cash/card business)
    daily_avg_rev  = total_revenue / 365.0
    ar_days        = random.uniform(5, 10)
    accounts_recv  = daily_avg_rev * ar_days
    total_assets   = closing_cash + inv_value_usd + accounts_recv

    # Liabilities
    daily_avg_cogs = float(cashflow_df["cogs_usd"].sum()) / 365.0
    ap_days        = random.uniform(30, 45)
    accounts_pay   = daily_avg_cogs * ap_days
    total_liab     = accounts_pay

    # Equity — derived as the balancing residual (Assets = Liabilities + Equity)
    # Decomposed for transparency:
    opening_inv_value = float((df["initial_stock"] * df["cost_price_usd"]).sum())
    opening_equity    = opening_cash + opening_inv_value
    total_equity      = total_assets - total_liab
    retained_earn     = total_equity - opening_equity

    bs_check = total_assets - total_liab - total_equity  # should be 0 by construction

    rows = [
        {"section": "ASSETS",      "line_item": "Cash & Cash Equivalents",          "amount_usd": round(closing_cash, 2)},
        {"section": "ASSETS",      "line_item": "Accounts Receivable",              "amount_usd": round(accounts_recv, 2)},
        {"section": "ASSETS",      "line_item": "Inventory — Active Stock (cost)",  "amount_usd": round(active_inv_value, 2)},
        {"section": "ASSETS",      "line_item": "Inventory — Dead Stock (cost)",    "amount_usd": round(dead_value, 2)},
        {"section": "ASSETS",      "line_item": "TOTAL ASSETS",                     "amount_usd": round(total_assets, 2)},
        {"section": "LIABILITIES", "line_item": "Accounts Payable (supplier)",      "amount_usd": round(accounts_pay, 2)},
        {"section": "LIABILITIES", "line_item": "TOTAL LIABILITIES",                "amount_usd": round(total_liab, 2)},
        {"section": "EQUITY",      "line_item": "Opening Owner Equity (cash + inv)","amount_usd": round(opening_equity, 2)},
        {"section": "EQUITY",      "line_item": "Retained Earnings (derived)",      "amount_usd": round(retained_earn, 2)},
        {"section": "EQUITY",      "line_item": "TOTAL EQUITY",                     "amount_usd": round(total_equity, 2)},
        {"section": "CHECK",       "line_item": "Assets minus (Liabilities + Equity)", "amount_usd": round(bs_check, 2)},
    ]
    return pd.DataFrame(rows), inv_value_usd, dead_value


# ---------------------------------------------------------------------------
# SECTION 13 — Owner recommendations
# ---------------------------------------------------------------------------

def build_recommendations(df, inv_df, cashflow_df, inv_value_usd, dead_value, pct_so):
    print("  [13] Building owner recommendations …")
    blended = df["gross_margin_pct"].mean()
    annual_ebitda = float(cashflow_df["ebitda_like_usd"].sum())
    dead_value_pct = dead_value / inv_value_usd if inv_value_usd > 0 else 0.0
    premium_share = (df["competitor_signal"] == "premium").mean()
    value_share   = (df["competitor_signal"] == "value").mean()

    cat_rev = inv_df.groupby("system_category")["revenue_usd"].sum().sort_values(ascending=False)
    top_cats = cat_rev.head(2).index.tolist()

    lines = [
        "=" * 70,
        "OWNER RECOMMENDATIONS — SportEdge 2026",
        "=" * 70,
        "",
    ]

    if blended < 0.50:
        lines += [
            "[MARGIN PRESSURE]",
            "Blended gross margin is below 50%. Reduce broad discounting and",
            "focus markdowns only on slow movers and true dead stock.",
            "",
        ]

    if annual_ebitda < 0:
        lines += [
            "[CASH WARNING]",
            "The management cash summary is negative. Slow down replenishment,",
            "tighten buying, and negotiate longer supplier payment terms.",
            "",
        ]
    else:
        lines += [
            "[CASH POSITION]",
            "The business remains cash-positive on a management basis. Keep",
            "replenishment tied to demand signals, not fixed calendar habits.",
            "",
        ]

    if dead_value_pct > 0.15:
        lines += [
            "[DEAD STOCK]",
            f"Dead stock is {dead_value_pct:.1%} of year-end inventory value.",
            "Bundle or clear these items to unlock working capital.",
            "",
        ]

    if pct_so > 0.10:
        lines += [
            "[STOCKOUT RISK]",
            f"{pct_so:.1%} of eligible SKUs stocked out. Raise reorder",
            "sensitivity on top-velocity items and use faster replenishment",
            "for core lines.",
            "",
        ]

    lines += [
        "[COMPETITION]",
        f"Premium-priced matched SKUs: {premium_share:.1%}.",
        f"Value-priced matched SKUs: {value_share:.1%}.",
        "Use markdowns selectively where price gaps and weak velocity overlap.",
        "",
        "[CATEGORY FOCUS]",
        f"Top revenue categories: {', '.join(top_cats)}.",
        "Bias future buying toward higher-turn, higher-margin categories",
        "and reduce breadth in weak tail items.",
        "",
        "[FINANCE NOTE]",
        "The cashflow output is a management cash summary, not a formal",
        "audited statement of cash flows. The balance sheet is a simplified",
        "management view using retained earnings proxy logic.",
        "",
        "=" * 70,
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    print("=" * 60)
    print("SportEdge — Synthetic Inventory Generator")
    print(f"Simulation period: {SIM_START} to {SIM_END}")
    print("=" * 60)

    # Core simulation
    df        = load_products()
    df        = assign_cost(df)
    df        = assign_stock(df)
    df        = assign_competitive(df)
    df        = assign_replenishment(df)
    inv_df    = simulate_inventory(df)
    labels_df = assign_labels(df, inv_df)

    # Financial layers
    opex_df, monthly_fixed, variable_rates = build_opex()
    cashflow_df, opening_cash = build_cashflow(inv_df, monthly_fixed, variable_rates)
    balance_df, inv_value_usd, dead_value = build_balance_sheet(
        df, inv_df, cashflow_df, opening_cash
    )

    # Stockout % for recommendations
    non_dead = df[~df["is_dead_stock_candidate"]]["sku_id"].tolist()
    so_skus  = inv_df[(inv_df["sku_id"].isin(non_dead)) & (inv_df["is_stockout"])]["sku_id"].nunique()
    pct_so   = so_skus / max(len(non_dead), 1)

    rec_text = build_recommendations(df, inv_df, cashflow_df, inv_value_usd, dead_value, pct_so)

    # Save and validate
    save_outputs(df, inv_df, labels_df, cashflow_df, balance_df, opex_df, rec_text)
    validate(df, inv_df, labels_df, cashflow_df, balance_df)

    print()
    print(rec_text)
    print("\nDone.")


if __name__ == "__main__":
    main()
