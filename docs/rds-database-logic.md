# RDS Database Logic

This project uses one PostgreSQL database on Amazon RDS:

```text
Database name: retail_radar
Engine: PostgreSQL
Main production schemas: core, intel
Optional/later schemas: marketing, model
```

The database is split into schemas so each part of the system has a clear responsibility.

```text
core      Your store data: products, SKUs, prices, stock, sales, purchase orders.
intel     Competitor intelligence from Apify scraping.
marketing Model recommendation outputs and campaign actions.
model     Planned model-ready views that join core + intel for IE2.
```

## Current Data Files

The main local data files are:

```text
data/real/inventory.csv
data/real/products.csv
data/real/competitor_prices.csv
data/real/financial_profile.json
```

Production scraping data is not imported from `competitor_prices.csv`. It is already stored in `intel.*` by the Apify webhook pipeline.

## Schema: core

`core` is the source of truth for your own store inventory.

### core.tenants

Purpose:

Stores the retailer/account. This allows the database to support more than one retailer later.

Filled by:

```text
infra/postgres/001_retail_core.sql
```

Example:

| slug | name | default_currency |
| --- | --- | --- |
| default | Default Retailer | USD |

Used by:

All `core` tables reference `tenant_id`.

### core.stores

Purpose:

Stores physical or online store locations.

Filled by:

```text
infra/postgres/001_retail_core.sql
```

Example:

| code | name | timezone | currency |
| --- | --- | --- | --- |
| MAIN | Main Store | Asia/Beirut | USD |

Used by:

`core.inventory_balances`, `core.inventory_movements`, `core.purchase_orders`, and `core.sales_transactions`.

### core.products

Purpose:

Stores product identity data that changes rarely: brand, product name, category, gender, season.

Filled from:

```text
data/real/inventory.csv
```

Column mapping:

| CSV column | DB column |
| --- | --- |
| brand | core.products.brand |
| product_name | core.products.name |
| system_category | core.products.category |
| gender | core.products.gender_target |

Example:

| brand | name | category | gender_target |
| --- | --- | --- | --- |
| Adidas | Adidas Galaxy 7 Women Running Shoes Black | footwear | women |

Notes:

`data/real/products.csv` has richer fields such as `product_key`, `collection_type`, and market pricing. The current deployed `core.products` table does not yet have columns for all of those fields.

### core.sku_variants

Purpose:

Stores the sellable SKU/variant. A product can have many variants by size, color, barcode, or style code.

Filled from:

```text
data/real/inventory.csv
data/real/products.csv
```

Column mapping:

| Source column | DB column |
| --- | --- |
| inventory.csv sku_id | core.sku_variants.sku_id |
| inventory.csv cost_price_usd | core.sku_variants.cost_price_usd |
| products.csv style_code | core.sku_variants.style_code |

Example:

| sku_id | style_code | cost_price_usd | status |
| --- | --- | ---: | --- |
| SP-6A627AE57E | ID8764 | 38.40 | active |

Relationship:

```text
core.products.id -> core.sku_variants.product_id
```

### core.prices

Purpose:

Stores current and historical prices. This is separate from SKUs so the system can know when prices changed.

Filled from:

```text
data/real/inventory.csv
```

Column mapping:

| CSV column | DB column |
| --- | --- |
| retail_price_usd | core.prices.amount |

Example:

| sku_id | price_type | amount | valid_from | valid_to |
| --- | --- | ---: | --- | --- |
| SP-6A627AE57E | retail | 81.96 | import time | null |

Relationship:

```text
core.sku_variants.id -> core.prices.variant_id
```

Logic:

The current price is the row where:

```sql
price_type = 'retail'
and valid_to is null
```

When price changes, the old row gets `valid_to`, and a new current row is inserted.

### core.inventory_balances

Purpose:

Stores current stock quantity per SKU per store.

Filled from:

```text
data/real/inventory.csv
```

Column mapping:

| CSV column | DB column |
| --- | --- |
| current_stock | core.inventory_balances.quantity_on_hand |

Example:

| store | sku_id | quantity_on_hand | quantity_reserved |
| --- | --- | ---: | ---: |
| MAIN | SP-6A627AE57E | 12 | 0 |

Relationship:

```text
core.stores.id -> core.inventory_balances.store_id
core.sku_variants.id -> core.inventory_balances.variant_id
```

Logic:

This table answers:

```text
How many units do we have right now?
```

### core.inventory_movements

Purpose:

Stores stock history. Every stock change should have a movement row.

Filled by:

Inventory import and later inventory operations.

Example rows:

| movement_type | quantity_delta | Meaning |
| --- | ---: | --- |
| full_import_adjustment | +12 | Stock set during CSV import |
| adjustment_in | +1 | Manual stock increase |
| adjustment_out | -1 | Manual stock decrease |
| sale | -1 | Unit sold |
| return | +1 | Unit returned |
| damaged | -1 | Unit damaged |
| purchase_receipt | +10 | New stock received |

Relationship:

```text
core.stores.id -> core.inventory_movements.store_id
core.sku_variants.id -> core.inventory_movements.variant_id
```

Logic:

This table answers:

```text
Why did stock change?
When did it change?
Who or what changed it?
```

### core.suppliers

Purpose:

Stores supplier/vendor information.

Filled from:

No current file fills this table.

Could be filled later from a supplier CSV or from a `supplier_name` column in inventory imports.

Example:

| name | contact_name | phone | email |
| --- | --- | --- | --- |
| Adidas Distributor | TBD | TBD | TBD |

Status:

Optional for now.

### core.purchase_orders

Purpose:

Stores purchase order headers for restocking.

Filled from:

No current file fills this table.

Example:

| po_number | supplier | store | status | expected_at |
| --- | --- | --- | --- | --- |
| PO-1001 | Adidas Distributor | MAIN | ordered | 2026-06-15 |

Status:

Optional for now.

### core.purchase_order_lines

Purpose:

Stores the individual SKU rows inside each purchase order.

Filled from:

No current file fills this table.

Example:

| po_number | sku_id | quantity_ordered | quantity_received | unit_cost_usd |
| --- | --- | ---: | ---: | ---: |
| PO-1001 | SP-6A627AE57E | 20 | 0 | 38.40 |

Relationship:

```text
core.purchase_orders.id -> core.purchase_order_lines.purchase_order_id
core.sku_variants.id -> core.purchase_order_lines.variant_id
```

Status:

Optional for now.

### core.sales_transactions

Purpose:

Stores sale headers. One row is one receipt/order.

Filled from:

No current file fills this table.

Example:

| external_sale_id | store | sold_at | channel | total_amount_usd |
| --- | --- | --- | --- | ---: |
| SALE-1001 | MAIN | 2026-05-29 14:10 | manual | 81.96 |

Status:

Optional for now, but important later for real sales velocity and model improvement.

### core.sales_transaction_lines

Purpose:

Stores the SKUs sold inside each sale.

Filled from:

No current file fills this table.

Example:

| sale | sku_id | quantity | unit_price_usd | unit_cost_usd | discount_pct |
| --- | --- | ---: | ---: | ---: | ---: |
| SALE-1001 | SP-6A627AE57E | 1 | 81.96 | 38.40 | 0 |

Relationship:

```text
core.sales_transactions.id -> core.sales_transaction_lines.sales_transaction_id
core.sku_variants.id -> core.sales_transaction_lines.variant_id
```

Status:

Optional for now, but important later for real sell-through, demand, and margin analysis.

### core.audit_logs

Purpose:

Stores actions performed by the system or UI, such as inventory import, SKU update, or archive.

Filled by:

Backend operations, not by CSV directly.

Example:

| actor | entity_type | entity_id | action |
| --- | --- | --- | --- |
| frontend | inventory_import | bulk | replace |

Status:

Useful for tracking changes.

## Schema: intel

`intel` stores competitor intelligence from Apify scraping. This was deployed before inventory.

### intel.shops

Purpose:

Stores competitor shops that are scraped.

Filled by:

```text
infra/postgres/001_intel_scraping.sql
infra/postgres/001_retail_core.sql
```

Example:

| shop_code | shop_name |
| --- | --- |
| adidas_lb | Adidas Lebanon |
| mikesport | Mike Sport |
| tchooz | Tchooz |

### intel.scrape_runs

Purpose:

Stores each Apify scraper run.

Filled by:

Apify webhook ingestion through EEP.

Example:

| shop_code | apify_run_id | apify_dataset_id | item_count | ingest_status |
| --- | --- | --- | ---: | --- |
| mikesport | run id | dataset id | 500 | succeeded |

Relationship:

```text
intel.shops.shop_code -> intel.scrape_runs.shop_code
```

### intel.competitor_product_snapshots

Purpose:

Stores all product rows from each scrape run. This is historical competitor data.

Filled by:

Apify webhook ingestion through EEP.

Example:

| shop_code | scrape_run_id | product_key | brand_name | product_name | competitor_price |
| --- | ---: | --- | --- | --- | ---: |
| mikesport | 123 | ADIDAS\|ID8764 | Adidas | Adidas Galaxy 7 | 80.00 |

Relationship:

```text
intel.scrape_runs.id -> intel.competitor_product_snapshots.scrape_run_id
```

### intel.competitor_products_latest

Purpose:

Stores the latest known competitor row per shop and product key.

Filled by:

Apify webhook ingestion through EEP.

Example:

| shop_code | product_key | brand_name | product_name | competitor_price | last_seen_at |
| --- | --- | --- | --- | ---: | --- |
| mikesport | ADIDAS\|ID8764 | Adidas | Adidas Galaxy 7 | 80.00 | latest scrape time |

Used by:

Market intelligence and model competitor signals.

Relationship:

```text
intel.shops.shop_code -> intel.competitor_products_latest.shop_code
```

## Schema: marketing

`marketing` stores model outputs and campaign actions. It may exist if the full retail schema was applied.

### marketing.recommendations

Purpose:

Stores IE2 decisions such as:

```text
HOLD
MARKDOWN
PROMOTE
CLEAR
```

Example:

| sku_id | recommendation | confidence | suggested_price_usd | status |
| --- | --- | ---: | ---: | --- |
| SP-6A627AE57E | HOLD | 0.98 | null | pending |

Relationship:

```text
core.sku_variants.id -> marketing.recommendations.variant_id
```

Status:

Later phase. Current inventory import does not fill this table.

### marketing.campaigns

Purpose:

Stores campaign drafts or published campaign actions created from recommendations.

Example:

| sku_id | channel | status | headline | starts_at |
| --- | --- | --- | --- | --- |
| SP-6A627AE57E | instagram | draft | Summer running drop | 2026-06-01 |

Relationship:

```text
marketing.recommendations.id -> marketing.campaigns.recommendation_id
core.sku_variants.id -> marketing.campaigns.variant_id
```

Status:

Later phase.

## Planned Schema: model

`model` is planned but not required for the current inventory import.

Purpose:

Expose simple model-ready rows that join `core` and `intel`.

Planned objects:

```text
model.current_inventory_inputs
model.current_competitor_signals
model.current_recommendation_inputs
model.feature_snapshots
```

Example planned view:

| sku_id | product_name | brand | category | retail_price_usd | cost_price_usd | current_stock | competitor_min_price |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| SP-6A627AE57E | Adidas Galaxy 7 Women Running Shoes Black | Adidas | footwear | 81.96 | 38.40 | 12 | 80.00 |

This gives IE2 one clean place to read from instead of joining many tables directly.

## Main Relationships

```text
core.tenants.id
  -> core.stores.tenant_id
  -> core.products.tenant_id
  -> core.sku_variants.tenant_id

core.products.id
  -> core.sku_variants.product_id

core.sku_variants.id
  -> core.prices.variant_id
  -> core.inventory_balances.variant_id
  -> core.inventory_movements.variant_id
  -> core.purchase_order_lines.variant_id
  -> core.sales_transaction_lines.variant_id
  -> marketing.recommendations.variant_id

core.stores.id
  -> core.inventory_balances.store_id
  -> core.inventory_movements.store_id
  -> core.purchase_orders.store_id
  -> core.sales_transactions.store_id

intel.shops.shop_code
  -> intel.scrape_runs.shop_code
  -> intel.competitor_product_snapshots.shop_code
  -> intel.competitor_products_latest.shop_code
```

## Import Logic

The current inventory import is based on:

```text
data/real/inventory.csv
```

When one row is imported:

```text
1. Create or update core.products.
2. Create or update core.sku_variants.
3. Create or update current core.prices retail row.
4. Create or update core.inventory_balances quantity_on_hand.
5. Insert core.inventory_movements row for the stock delta.
6. Insert core.audit_logs row for the import action.
```

Example:

```text
CSV row:
SP-6A627AE57E, Adidas, Adidas Galaxy 7 Women Running Shoes Black, footwear, women, 81.96, 38.40, current_stock 12

DB result:
core.products: Adidas Galaxy 7 product
core.sku_variants: SKU SP-6A627AE57E
core.prices: retail price 81.96
core.inventory_balances: quantity_on_hand 12
core.inventory_movements: +12 import movement
```

## Verification Queries

Use these after importing inventory:

```sql
select 'active_skus' as check_name, count(*)
from core.sku_variants
where status = 'active'
union all
select 'inventory_balances', count(*)
from core.inventory_balances
union all
select 'inventory_movements', count(*)
from core.inventory_movements
union all
select 'current_retail_prices', count(*)
from core.prices
where price_type = 'retail' and valid_to is null;
```

Expected after importing the current inventory CSV:

```text
active_skus: 400
inventory_balances: 400
current_retail_prices: 400
inventory_movements: 400 or more
```

`inventory_movements` can be higher than 400 if the import was run more than once or if manual edits were made.

