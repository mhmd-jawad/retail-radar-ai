# Apify -> PostgreSQL Pipeline

The active database target is the main Retail Radar PostgreSQL schema:

```text
infra/postgres/001_intel_scraping.sql
```

Scraped data is stored in the `intel` schema:

```text
intel.shops
intel.scrape_runs
intel.competitor_product_snapshots
intel.competitor_products_latest
```

The older `apify/db/schema.sql` file is a standalone prototype schema. Do not use it for the main app unless you intentionally want a separate `public.*` scraping database.

## Operating Model

Use this flow:

1. Apify schedule runs each shop actor.
2. Apify webhook calls EEP:

```text
POST /webhooks/apify/run-succeeded?shop=mikesport
```

3. EEP fetches the finished Apify run and dataset.
4. EEP writes the run to `intel.scrape_runs`.
5. EEP writes append-only history to `intel.competitor_product_snapshots`.
6. EEP upserts current state into `intel.competitor_products_latest`.

## Local Manual Sync

Manual sync is useful before wiring webhooks:

```powershell
python apify\tools\sync_to_postgres.py --run-id APIFY_RUN_ID --shop mikesport
```

Required environment:

```text
APIFY_TOKEN=your-token
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/retail_radar
```

The script applies `infra/postgres/001_intel_scraping.sql` unless `--skip-schema` is passed.

## Scheduled Sync Fallback

If you do not want webhooks yet, use the scheduled sync script:

```powershell
copy apify\config\shops.example.json apify\config\shops.json
```

Fill in each `actor_id` or `task_id`, then run:

```powershell
python apify\tools\sync_scheduled_runs_to_postgres.py --shops all
```

## Webhook Endpoint

Run EEP:

```powershell
uvicorn eep.main:app --host 0.0.0.0 --port 8000
```

Expose it publicly for Apify:

```powershell
ngrok http 8000
```

Apify webhook:

```text
Event: ACTOR.RUN.SUCCEEDED
URL: https://YOUR_PUBLIC_DOMAIN/webhooks/apify/run-succeeded?shop=mikesport
Header: x-webhook-secret: YOUR_SECRET
```

Set the same secret in EEP:

```text
APIFY_WEBHOOK_SECRET=YOUR_SECRET
```

## Query Guidance

Use `intel.competitor_products_latest` for:

- dashboard current competitor prices
- product matching by `style_code` or `sku_id`
- current stock/sale signals

Use `intel.competitor_product_snapshots` for:

- daily history
- price trend charts
- availability trend analysis
- audits and reruns

Do not create:

- one table per day
- one table per shop
- one table per shop per day

Use shared history/latest tables with `shop_code` and timestamps.
