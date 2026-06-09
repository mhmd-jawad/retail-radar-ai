# Full-Stack Docker Deployment

This project has two Compose entry points built from the same application
containers:

| File | Purpose | Database |
| --- | --- | --- |
| `infra/docker-compose.yml` | Full local development stack | `DATABASE_URL` from repo `.env` |
| `infra/docker-compose.aws.yml` | Lightsail deployment stack | Existing Amazon RDS PostgreSQL |

Do not run a PostgreSQL container on Lightsail for the AWS deployment. The
deployed database remains the RDS instance reached through `DATABASE_URL`.

## What Is Deployable Now

The normal AWS command runs:

- `eep`: public API, Apify webhook receiver, and in-process IE2 model inference.
- `frontend`: built React dashboard served by Nginx.
- `caddy`: HTTPS termination and routing for the dashboard and EEP API.
- `prometheus` and `grafana`: internal monitoring, bound only to localhost.

The optional `full` profile additionally runs:

- `ie1_market_intelligence`: standalone competitor-signal API.
- `ie2_decision_intelligence`: standalone model API at the protected `/ie2/` route.
- `ie3_campaign_creative`: internal creative-generation API.

EEP already embeds the IE2 model. Do not start the standalone IE2 container on
a small server unless you specifically need its direct API; it loads a second
copy of the model into memory.
In the normal AWS stack, Caddy routes the dashboard's `/ie2/health` check to
the model-enabled EEP container; direct `/ie2/*` model API routes need the
optional `full` profile.

## Existing AWS Database Compatibility

The already deployed scraping database contains only:

```text
intel.shops
intel.scrape_runs
intel.competitor_product_snapshots
intel.competitor_products_latest
```

That is enough for the current automatic scraper flow:

```text
Apify scheduled run -> Apify success webhook -> Caddy -> EEP -> RDS intel.*
```

EEP reads `intel.scrape_runs` and `intel.competitor_products_latest` from RDS
for the Ops dashboard and for live competitor inputs to model requests. When
no database is configured, those code paths fall back to local output files
for offline development.

Do not apply `infra/postgres/001_retail_core.sql` merely to deploy the
dashboard or keep scraping. It adds the later inventory and marketing model:
`core.*` and `marketing.*`. Apply it only when you are ready to enable
inventory editing and campaign persistence in RDS.

## Local Full Stack

From the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
# Put your real DATABASE_URL and testing secrets in .env.
docker compose -f infra\docker-compose.yml up -d --build
docker compose -f infra\docker-compose.yml ps
```

Open:

| Component | URL |
| --- | --- |
| Dashboard | `http://localhost:4173` |
| EEP API/docs | `http://localhost:8000/docs` |
| IE1 | `http://localhost:8001/health` |
| IE2 | `http://localhost:8002/health` |
| IE3 | `http://localhost:8003/health` |
| Adminer | `http://localhost:8080` |
| Prometheus | `http://localhost:9090` |
| Grafana | `http://localhost:3001` |

The local Compose file now points app services at `DATABASE_URL` from `.env`.
The built dashboard uses same-origin API paths, so `http://localhost:4173/auth/*`,
`/inventory/*`, `/outcomes/*`, and recommendation calls proxy
through Docker to the right backend service.
If you want a disposable local PostgreSQL instead, start the optional database
profile and set `.env` to `postgresql://postgres:postgres@postgres:5432/retail_radar`
for the Docker app containers:

```powershell
docker compose -f infra\docker-compose.yml --profile local-db up -d postgres adminer
```

## Update The Existing Lightsail Deployment

On the Lightsail Ubuntu instance, enter the cloned repository:

```bash
cd ~/retail-radar-ai
git pull origin dev
```

Keep the existing `.env`. Edit it only to confirm these values:

```env
DATABASE_URL=postgresql://retail_admin:URL_ENCODED_PASSWORD@YOUR_RDS_ENDPOINT:5432/retail_radar?sslmode=require
RETAIL_AUTO_INIT_DB=false
RETAIL_TENANT_SLUG=default
RETAIL_STORE_CODE=MAIN
APIFY_TOKEN=YOUR_CURRENT_APIFY_TOKEN
APIFY_WEBHOOK_SECRET=YOUR_CURRENT_WEBHOOK_SECRET
WEBHOOK_DOMAIN=63.184.254.17.sslip.io
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=CHANGE_TO_A_LONG_PASSWORD
IE2_API_KEY=CHANGE_TO_A_LONG_RANDOM_KEY
```

Deploy the low-memory production set. This preserves RDS data, the existing
Caddy certificate volume, and the working Apify webhook endpoint:

```bash
docker compose -f infra/docker-compose.aws.yml up -d --build eep frontend caddy prometheus grafana
docker compose -f infra/docker-compose.aws.yml ps
curl -fsS "https://$WEBHOOK_DOMAIN/health"
```

The dashboard is then served at:

```text
https://63.184.254.17.sslip.io/
```

Your existing Apify webhook URL remains:

```text
https://63.184.254.17.sslip.io/webhooks/apify/run-succeeded?shop=SHOP_CODE
```

## Verify Automatic Scrapes

No terminal command is needed for each scheduled scrape. After the next Apify
schedule succeeds, check the deployed dashboard Ops page or run a verification
query when diagnosing:

```bash
psql "$DATABASE_URL" -c "select shop_code, apify_run_id, item_count, ingest_status, created_at from intel.scrape_runs order by created_at desc limit 10;"
```

A new successful row proves that Apify called EEP and EEP saved that run in
RDS. The dashboard uses the same RDS data through EEP.

## Enable The Later Full Services

Before using inventory editing or IE3 campaign persistence in AWS:

1. Take an RDS snapshot.
2. Apply `infra/postgres/001_retail_core.sql` once to the RDS database.
3. Add required IE3 keys to `.env`: `OPENROUTER_API_KEY`, and whichever image
   or publishing provider values you choose.
4. Start the optional containers:

```bash
docker compose -f infra/docker-compose.aws.yml --profile full up -d --build
```

IE1 and IE3 stay internal because they do not yet enforce API authentication.
IE2 is reachable through `https://YOUR_DOMAIN/ie2/` only in the full profile
and its recommendation endpoints require `X-API-Key: IE2_API_KEY`.

On the current 2 GB Lightsail instance, run the normal production set first.
If the full profile causes memory pressure, keep EEP model inference and move
optional services to a larger instance or a later separate service deployment.

## Secrets

Never commit `.env`. An Apify token previously existed in `eep/.env.example`;
the example file is now sanitized. If that token was real, revoke it in Apify,
create a replacement token, update `.env` on Lightsail, and recreate EEP:

```bash
docker compose -f infra/docker-compose.aws.yml up -d --force-recreate eep
```

