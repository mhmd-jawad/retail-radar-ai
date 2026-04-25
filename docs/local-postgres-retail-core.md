# Local PostgreSQL Retail Core

This project now has a local-first retail inventory database that can later move to AWS RDS or Aurora PostgreSQL without changing the frontend contract.

## Tables

The schema lives in:

```text
infra/postgres/001_retail_core.sql
```

Main retail tables:

- `core.tenants`
- `core.stores`
- `core.suppliers`
- `core.products`
- `core.sku_variants`
- `core.prices`
- `core.inventory_balances`
- `core.inventory_movements`
- `core.purchase_orders`
- `core.purchase_order_lines`
- `core.sales_transactions`
- `core.sales_transaction_lines`
- `core.audit_logs`

Competitor intelligence tables:

- `intel.shops`
- `intel.scrape_runs`
- `intel.competitor_product_snapshots`
- `intel.competitor_products_latest`

Decision and campaign tables:

- `marketing.recommendations`
- `marketing.campaigns`

## Start Local PostgreSQL

From the repo root:

```powershell
docker compose -f infra\docker-compose.local.yml up -d
```

This starts:

- PostgreSQL on `localhost:5432`
- Adminer on `http://localhost:8080`

Adminer login:

```text
System: PostgreSQL
Server: postgres
Username: postgres
Password: postgres
Database: retail_radar
```

If you connect from VS Code, DBeaver, or pgAdmin on the host machine, use:

```text
postgresql://postgres:postgres@localhost:5432/retail_radar
```

## Run EEP With DB Access

Install the EEP dependencies:

```powershell
pip install -r eep\requirements.txt
```

Run EEP:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/retail_radar"
$env:RETAIL_AUTO_INIT_DB="true"
uvicorn eep.main:app --port 8000 --reload
```

`RETAIL_AUTO_INIT_DB=true` makes EEP apply the schema if the DB is empty or missing tables. The schema is idempotent.

## Run Frontend

Create or update `frontend/.env`:

```text
VITE_DATA_MODE=eep-live
VITE_API_BASE_URL=http://localhost:8000
VITE_IE2_BASE_URL=http://localhost:8002
VITE_API_KEY=ie2-local-postman-key
```

Then:

```powershell
cd frontend
npm run dev
```

Open the dashboard and go to:

```text
/inventory
```

The `Manage inventory` tab uses PostgreSQL through EEP.

## Inventory CSV Headers

Bulk import accepts these headers:

```text
sku_id,product_name,brand,category,current_stock,retail_price_usd,cost_price_usd,barcode,style_code,color,size,gender_target,season,reorder_point,reorder_quantity,supplier_name,notes
```

Required:

- `sku_id`
- `product_name`
- `brand`
- `category`
- `current_stock`
- `retail_price_usd`
- `cost_price_usd`

Import modes:

- `upsert`: add new SKUs and update existing SKUs
- `replace`: upsert the uploaded SKUs and archive active SKUs not present in the upload

Stock changes are written to `core.inventory_movements`; current stock is stored in `core.inventory_balances`.

## AWS Later

For AWS, use the same schema against:

- Amazon RDS PostgreSQL, or
- Aurora PostgreSQL

Set only:

```text
DATABASE_URL=your-production-postgres-url
RETAIL_AUTO_INIT_DB=false
```

Then run the schema once during deployment or migration. The frontend keeps calling EEP; only the backend database URL changes.
