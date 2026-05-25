# Fully Automatic Apify -> Supabase

Current scraping/webhook deployment should use the EEP webhook endpoint and the four-table schema in `infra/postgres/001_intel_scraping.sql`. The broader retail-core schema is for later inventory and marketing features.
This Supabase Edge Function path is optional/legacy and still uses the standalone `apify/db/schema.sql` public tables.

Yes, this can be fully automatic.

Use this architecture:

1. Apify scheduled task runs each shop actor daily
2. Apify webhook fires on `ACTOR.RUN.SUCCEEDED`
3. Supabase Edge Function receives the webhook
4. the function fetches the run dataset from Apify
5. the function writes into your Supabase Postgres tables

## Files

- `apify/db/schema.sql`
- `apify/supabase/functions/apify-run-sync/index.ts`

## What to deploy

### 1. Supabase database

Create a Supabase project and run:

- `apify/db/schema.sql`

### 2. Supabase Edge Function

Deploy:

- `apify/supabase/functions/apify-run-sync/index.ts`

This function expects:

- `APIFY_TOKEN`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `WEBHOOK_SECRET`

### 3. Apify webhook

Create one webhook per scheduled task.

Event:

- `ACTOR.RUN.SUCCEEDED`

Request URL pattern:

```text
https://<your-project-ref>.supabase.co/functions/v1/apify-run-sync?shop=mikesport
```

Use the correct `shop` query string for each actor:

- `adidas_lb`
- `mikesport`
- `tchooz`
- `shoesworld`
- `citysport`
- `kix`
- `marka_store`

Add a webhook header:

```json
{
  "x-webhook-secret": "YOUR_SHARED_SECRET"
}
```

## Result

After every successful scheduled Apify run:

- the dataset is read automatically
- `scrape_runs` gets one row for the run
- `competitor_product_snapshots` gets the historical rows
- `competitor_products_latest` gets updated to the newest state

No manual syncing is needed after setup.

## Alternative

If you do not want webhooks, use:

- `apify/tools/sync_scheduled_runs_to_postgres.py`

as a cron job.

That is also automatic, but it runs on a schedule instead of immediately after each successful Apify task.
