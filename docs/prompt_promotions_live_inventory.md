# Prompt: Switch Promotions to Live Inventory Data Only

## Context

The Promotions page (`frontend/src/pages/Promotions.tsx`) currently works in `eep-live` mode,
calling `GET /report` on the EEP service (port 8000). The EEP report is built by
`build_frontend_report()` in `eep/frontend_bridge.py`, which reads inventory data from
CSV files on disk (`data/real/inventory.csv`, `data/real/products.csv`, `data/reports/report.json`).

The PostgreSQL database (`retail_radar` at localhost:5432) currently has ~155 items seeded
from those same CSV files as a temporary placeholder. These are NOT live — they are static CSV seeds.

The frontend `.env.local` has `VITE_DATA_MODE=eep-live`, so all pages already call the real EEP API.

## What needs to change

When the live inventory database is deployed and populated with real store data, the Promotions
page must stop using the CSV-based report and instead read directly from the live PostgreSQL
inventory table.

### The key function to update: `build_frontend_report()` in `eep/frontend_bridge.py`

Currently it calls:
- `load_inventory_index()` — reads `data/real/inventory.csv` into a dict keyed by sku_id
- `load_products_index()` — reads `data/real/products.csv`
- `load_raw_report()` — reads `data/reports/report.json` (the pre-generated ML report)

The promotions section inside `build_frontend_report()` (lines ~550–620) iterates over
`promotions_raw = raw_report.get("promotions", {})` from the JSON report file.

### Target state

Replace the CSV/JSON sources with live DB queries:

1. **Inventory items** — use `eep/retail_db.py`'s `list_inventory_items()` function (already exists)
   instead of `load_inventory_index()`. This returns real-time stock, prices, status from PostgreSQL.

2. **Promotion recommendations (promote/markdown/clearance/hold)** — these come from the ML report
   (`data/reports/report.json`). Once the ML pipeline runs on live data and writes a fresh report to
   that path (or to a `reports` table in PostgreSQL), `build_frontend_report()` should read from there.
   For now, the simplest connection is:
   - Keep reading recommendations from `report.json` (it's the ML output)
   - But use the live DB for prices, stock levels, and SKU metadata (override CSV values with DB values)

3. **Remove the 155 seeded items** from PostgreSQL when live data arrives:
   ```sql
   TRUNCATE TABLE inventory.vendor_skus CASCADE;
   -- Then insert live items via the /inventory/items POST endpoint or a new seed script
   ```

### Specific code change in `build_frontend_report()`

Replace the static CSV lookup fallback with a live DB lookup:

```python
# In build_frontend_report(), after loading inventory_rows from CSV:
from eep.retail_db import list_inventory_items

live_items = list_inventory_items()  # reads from PostgreSQL
live_db_index = {item["sku_id"]: item for item in live_items}

# Then when building each SKU's `transformed` dict, prefer live_db_index over inventory_rows:
inventory_row = live_db_index.get(sku_id) or inventory_rows.get(sku_id, {})
```

This single change makes prices and stock levels come from the live DB while keeping
ML-generated recommendations (promote/markdown/clearance/hold decisions) from the report file.

## Files to change

- `eep/frontend_bridge.py` — update `build_frontend_report()` to use live DB via `list_inventory_items()`
- `eep/retail_db.py` — verify `list_inventory_items()` returns all fields needed (`retail_price_usd`,
  `cost_price_usd`, `current_stock`, `initial_stock`, `brand`, `product_name`, `system_category`)
- No frontend changes needed — the frontend already calls EEP and handles the response shape

## How to test after change

```powershell
# 1. Make sure EEP is running with live DB connected
Invoke-RestMethod "http://localhost:8000/inventory/db/status"
# Expect: connected=true, item_count > 0 (live items, not 155 seeds)

# 2. Hit the report endpoint and check SKU IDs match live DB
Invoke-RestMethod "http://localhost:8000/report" | ConvertTo-Json -Depth 3

# 3. Open http://localhost:8081/promotions — actions should persist without "applied locally" toast
```

## What the user will need to do before this prompt is used

1. Deploy/connect the live inventory database
2. Populate it with real store inventory (not the CSV seed)
3. Ensure the ML pipeline (StylePulse / `stylepulse/`) has run and written a fresh `report.json`
   based on the live inventory — OR wire `build_frontend_report()` to query ML recommendations
   from a DB table instead of the JSON file
