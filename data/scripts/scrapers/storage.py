"""
Saves scraped products to CSV and JSON — same schema as existing data/outputs/ files.
Also saves to competitor_prices.db (SQLite) for IE1 to read.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
from .base import ScrapedProduct

OUTPUTS_DIR = Path(__file__).parents[2] / "outputs"
DB_PATH = OUTPUTS_DIR / "competitor_prices.db"


def save_to_csv_and_json(products: list[ScrapedProduct], retailer_name: str) -> None:
    """Save scraped products to CSV + JSON in data/outputs/."""
    if not products:
        print(f"  [storage] No products to save for {retailer_name}")
        return

    rows = [p.to_dict() for p in products]
    df = pd.DataFrame(rows)

    # Serialize list columns to JSON strings for CSV
    df["sizes_available"] = df["sizes_available"].apply(json.dumps)

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    csv_path  = OUTPUTS_DIR / f"{retailer_name}_{date_str}_records.csv"
    json_path = OUTPUTS_DIR / f"{retailer_name}_{date_str}_records.json"

    df.to_csv(csv_path, index=False)

    # JSON: restore sizes_available back to list
    for row in rows:
        if isinstance(row["sizes_available"], str):
            row["sizes_available"] = json.loads(row["sizes_available"])

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    print(f"  [storage] Saved {len(products)} products → {csv_path.name}, {json_path.name}")


def save_to_sqlite(products: list[ScrapedProduct]) -> None:
    """
    Insert scraped products into competitor_prices.db.
    IE1 reads from this database — never scrapes live.
    Table: competitor_prices (matches spec schema exactly)
    """
    if not products:
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS competitor_prices (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            sku_id                TEXT,
            style_code            TEXT NOT NULL,
            competitor_name       TEXT NOT NULL,
            competitor_price      REAL,
            competitor_sale_price REAL,
            is_on_sale            INTEGER DEFAULT 0,
            discount_pct          REAL,
            availability          TEXT,
            scraped_at            TEXT NOT NULL,
            url                   TEXT,
            data_valid            INTEGER DEFAULT 1,
            retailer_name         TEXT,
            product_name          TEXT,
            currency              TEXT,
            colorway              TEXT,
            category              TEXT,
            gender_target         TEXT,
            sizes_available       TEXT
        )
    """)

    rows = []
    for p in products:
        rows.append((
            p.sku_id,
            p.style_code,
            p.competitor_name,
            p.competitor_price,
            p.competitor_sale_price,
            1 if p.is_on_sale else 0,
            p.discount_pct,
            p.availability,
            p.scraped_at,
            p.source_url,
            1 if p.data_valid else 0,
            p.retailer_name,
            p.product_name,
            p.currency,
            p.colorway,
            p.category,
            p.gender_target,
            json.dumps(p.sizes_available),
        ))

    cur.executemany("""
        INSERT INTO competitor_prices (
            sku_id, style_code, competitor_name,
            competitor_price, competitor_sale_price, is_on_sale, discount_pct,
            availability, scraped_at, url, data_valid,
            retailer_name, product_name, currency, colorway, category,
            gender_target, sizes_available
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)

    conn.commit()
    conn.close()
    print(f"  [storage] Inserted {len(products)} rows into competitor_prices.db")


def save_all(products: list[ScrapedProduct], retailer_name: str) -> None:
    """Save to both CSV/JSON files and SQLite DB."""
    save_to_csv_and_json(products, retailer_name)
    save_to_sqlite(products)
