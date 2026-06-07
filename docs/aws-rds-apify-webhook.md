# AWS RDS + Apify Webhook Runbook

The scraping/webhook deployment uses one production database target:

```text
infra/postgres/001_intel_scraping.sql
```

Scraper data lands in:

```text
intel.shops
intel.scrape_runs
intel.competitor_product_snapshots
intel.competitor_products_latest
```

Do not use `data/outputs/competitor_prices.db` for production. It is an old local SQLite artifact.

The larger `infra/postgres/001_retail_core.sql` schema is reserved for later inventory, sales, and marketing work. Do not apply it to the current AWS database while you are deploying only the scraping pipeline.

## Local Development

### 1. Start local PostgreSQL

```powershell
docker compose -f infra\docker-compose.local.yml up -d
```

Local URL:

```text
postgresql://postgres:postgres@localhost:5432/retail_radar
```

### 2. Create your local env file

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set:

```text
APIFY_TOKEN=your_real_apify_token
APIFY_WEBHOOK_SECRET=a_long_random_secret
```

Load it in PowerShell:

```powershell
Get-Content .env | ForEach-Object {
  if ($_ -and $_ -notmatch '^#') {
    $name, $value = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable($name, $value, 'Process')
  }
}
```

### 3. Install backend tooling

```powershell
pip install -r eep\requirements.txt
pip install -r apify\tools\requirements.txt
```

### 4. Run EEP locally

```powershell
uvicorn eep.main:app --host 0.0.0.0 --port 8000 --reload
```

Check:

```powershell
curl http://localhost:8000/health
```

### 5. Test DB ingest without webhooks

Use a real Apify run id:

```powershell
python apify\tools\sync_to_postgres.py --run-id APIFY_RUN_ID --shop mikesport
```

Or replay through the EEP endpoint:

```powershell
curl -X POST "http://localhost:8000/webhooks/apify/replay-run?shop=mikesport&run_id=APIFY_RUN_ID" -H "x-webhook-secret: YOUR_SECRET"
```

### 6. Test live Apify webhooks locally

Apify cannot call `localhost`, so expose EEP with a tunnel:

```powershell
ngrok http 8000
```

Create an Apify webhook for each actor/task:

```text
Event: ACTOR.RUN.SUCCEEDED
URL: https://YOUR_NGROK_DOMAIN/webhooks/apify/run-succeeded?shop=mikesport
Header: x-webhook-secret: YOUR_SECRET
```

Use the matching `shop` value for each actor:

```text
adidas_lb
mikesport
tchooz
shoesworld
citysport
kix
marka_store
```

After a successful actor run, verify rows:

```sql
select * from intel.scrape_runs order by created_at desc limit 10;
select count(*) from intel.competitor_product_snapshots;
select count(*) from intel.competitor_products_latest;
```

## Low-Cost AWS Deployment

Production layout:

```text
Apify scheduled actor
  -> HTTPS webhook
  -> Amazon Lightsail Ubuntu instance running Caddy + EEP
  -> private Amazon RDS PostgreSQL instance
```

RDS is private. Do not change `Public access` to `Yes` and do not allow database port `5432` from the internet. The Lightsail instance reaches RDS by VPC peering in the same AWS Region.

### 1. RDS PostgreSQL Settings

Create RDS in Europe (Frankfurt), `eu-central-1`:

```text
Engine: PostgreSQL
Instance: db.t4g.micro, or db.t3.micro if t4g is unavailable
Availability: Single DB instance / Single-AZ
Storage: 20 GB General Purpose SSD
Storage autoscaling: off
Initial database name: retail_radar
Public access: no
VPC: Default VPC
Security group: retail-radar-rds-sg
Port: 5432
RDS Proxy: off
Performance Insights: off
Enhanced Monitoring: off
Automated backups: on, 1 day
Cross-Region replication: off
```

Save the database endpoint, master username, and master password securely when RDS becomes available.

### 2. Create the Webhook Server

In Amazon Lightsail, create an instance in the same region, Europe (Frankfurt):

```text
Platform: Linux/Unix
Blueprint: OS Only / Ubuntu 24.04 LTS
Plan: Nano 0.5 GB Linux with public IPv4 ($5/month)
Instance name: retail-radar-webhook
```

The 0.5 GB plan is the lowest-cost public IPv4 option. If Docker builds or the API are unreliable after adding swap, upgrade the instance to the 1 GB plan.

Attach a Lightsail static IP to the instance. In the Lightsail firewall allow:

```text
SSH TCP 22: your current IP only
HTTP TCP 80: anywhere
HTTPS TCP 443: anywhere
```

Never add PostgreSQL port `5432` to the Lightsail public firewall.

### 3. Connect Lightsail Privately To RDS

Enable Lightsail VPC peering:

```text
Lightsail console -> Account -> Advanced -> VPC peering
Region: Europe (Frankfurt) / eu-central-1 -> Enable
```

Copy the Lightsail instance private IPv4 address. Then in the RDS security group `retail-radar-rds-sg`, add this inbound rule:

```text
Type: PostgreSQL
Protocol: TCP
Port: 5432
Source: LIGHTSAIL_PRIVATE_IP/32
Description: retail-radar-webhook private access
```

### 4. Install Software On Lightsail

Connect using the Lightsail browser SSH terminal:

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-v2 postgresql-client
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
exit
```

Reconnect after `exit`, then place this project on the server by cloning your repository:

```bash
git clone YOUR_PRIVATE_REPOSITORY_URL retail-radar-ai
cd retail-radar-ai
```

The repository must include the AWS deployment files and ingestion code from this project. Do not commit or upload `.env`.

### 5. Configure The Production Environment

From the project directory on Lightsail:

```bash
cp .env.example .env
nano .env
```

Set:

```text
DATABASE_URL=postgresql://YOUR_DB_USERNAME:YOUR_URL_ENCODED_PASSWORD@YOUR_RDS_ENDPOINT:5432/retail_radar?sslmode=require
RETAIL_AUTO_INIT_DB=false
RETAIL_TENANT_SLUG=default
RETAIL_STORE_CODE=MAIN
APIFY_TOKEN=YOUR_APIFY_TOKEN
APIFY_WEBHOOK_SECRET=YOUR_LONG_RANDOM_SECRET
WEBHOOK_DOMAIN=YOUR_LIGHTSAIL_STATIC_IP.sslip.io
OPENROUTER_API_KEY=
REPLICATE_API_KEY=
```

Generate a webhook secret on Lightsail with:

```bash
openssl rand -hex 32
chmod 600 .env
```

### 6. Apply The Database Schema

Still on Lightsail, test the private database connection and create the project tables:

```bash
export RDS_ENDPOINT="YOUR_RDS_ENDPOINT"
export PGUSER="YOUR_DB_USERNAME"
export PGDATABASE="retail_radar"
read -s -p "RDS password: " PGPASSWORD
export PGPASSWORD
echo
psql "host=$RDS_ENDPOINT port=5432 dbname=$PGDATABASE user=$PGUSER sslmode=require" -c "select now();"
psql "host=$RDS_ENDPOINT port=5432 dbname=$PGDATABASE user=$PGUSER sslmode=require" -f infra/postgres/001_intel_scraping.sql
psql "host=$RDS_ENDPOINT port=5432 dbname=$PGDATABASE user=$PGUSER sslmode=require" -c "\dt intel.*"
unset PGPASSWORD
```

Only these four scraper ingestion tables are created:

```text
intel.shops
intel.scrape_runs
intel.competitor_product_snapshots
intel.competitor_products_latest
```

### 7. Deploy EEP And HTTPS

For an initial HTTPS name without purchasing a domain, if the Lightsail static IP is `18.194.12.34`, set:

```text
WEBHOOK_DOMAIN=18.194.12.34.sslip.io
```

Start the production containers:

```bash
docker compose -f infra/docker-compose.aws.yml up -d --build
docker compose -f infra/docker-compose.aws.yml ps
docker compose -f infra/docker-compose.aws.yml logs -f
```

Verify in a browser:

```text
https://YOUR_WEBHOOK_DOMAIN/health
```

Do not use `/inventory/*` endpoints in this scraping-only deployment. Those routes belong to the optional full retail-core schema and are not needed for Apify webhooks.

### 8. Load A Known Test Run Into AWS

From local PowerShell, use the Tchooz run that already loaded successfully into local Docker:

```powershell
$domain = "https://YOUR_WEBHOOK_DOMAIN"
$secret = "YOUR_APIFY_WEBHOOK_SECRET"
Invoke-RestMethod -Method Post -Uri "$domain/webhooks/apify/replay-run?shop=tchooz&run_id=sWCKOfvZqTadlwemg" -Headers @{ "x-webhook-secret" = $secret }
```

Verify from the Lightsail SSH terminal:

```bash
export PGPASSWORD="YOUR_RDS_PASSWORD"
psql "host=YOUR_RDS_ENDPOINT port=5432 dbname=retail_radar user=YOUR_DB_USERNAME sslmode=require" -c "select id, shop_code, apify_run_id, item_count, ingest_status, created_at from intel.scrape_runs order by created_at desc limit 10;"
psql "host=YOUR_RDS_ENDPOINT port=5432 dbname=retail_radar user=YOUR_DB_USERNAME sslmode=require" -c "select count(*) from intel.competitor_product_snapshots;"
psql "host=YOUR_RDS_ENDPOINT port=5432 dbname=retail_radar user=YOUR_DB_USERNAME sslmode=require" -c "select count(*) from intel.competitor_products_latest;"
unset PGPASSWORD
```

### 9. Configure Apify

For each scheduled actor/task:

```text
Event: ACTOR.RUN.SUCCEEDED
URL: https://YOUR_DOMAIN/webhooks/apify/run-succeeded?shop=SHOP_CODE
Header: x-webhook-secret: YOUR_SECRET
```

When the actor finishes:

1. EEP receives the webhook.
2. EEP fetches the actor run and dataset from Apify.
3. Rows are inserted into `intel.scrape_runs`.
4. Historical rows are upserted into `intel.competitor_product_snapshots`.
5. Current rows are upserted into `intel.competitor_products_latest`.

### 10. Cost Guardrails

Create an AWS Budget alert immediately:

```text
Budget type: monthly cost
Amount: 1 USD or 5 USD
Email: your email
```

Avoid:

```text
Multi-AZ RDS
NAT Gateway
Load balancers
More than one RDS instance
Storage above 20 GB
Storage autoscaling
Leaving old snapshots/backups around
RDS public access
```
