# Retail Radar AI

Retail Radar AI is a production-deployed, multi-service AI decision-support platform for small and mid-size  retailers. It combines live inventory management, competitor-price intelligence, rules-based and ML-based recommendations, campaign creative generation, financial monitoring, social account wiring, and an assistant interface into one cloud-hosted dashboard.

The final deployed system runs on AWS using a two-node Kubernetes cluster, Amazon RDS PostgreSQL, Apify scraping/webhooks, GitHub Actions CI/CD, GHCR container images, a Lightsail load balancer, and the public domain:

- Production app: `https://www.retailradar.site/login`
- Root domain: `https://retailradar.site`
- Load balancer DNS: `e43c88ab0453c69b919ea0b68ffac616-860150828.eu-central-1.elb.amazonaws.com`
- Main cloud region: AWS Europe, Frankfurt, `eu-central-1`

This README is the high-level project and deployment reference. More focused runbooks are in `docs/`.

## Professor Access And Credentials

A dedicated read-only IAM user (`DrAmmar`) has been created for viewing purposes only. This account has access exclusively to **Amazon Lightsail** (servers, databases, networking, snapshots) — no other AWS services are accessible. No changes can be made through this account.

### AWS Console — Lightsail (Frankfurt Region)

| Field | Value |
|---|---|
| Sign-in URL | `https://431071878442.signin.aws.amazon.com/console` |
| Account ID | `431071878442` |
| IAM Username | `DrAmmar` |
| Password | `Password@123` |
| Region | Europe (Frankfurt) — `eu-central-1` |
| Access scope | Lightsail only (view instances, databases, networking, snapshots) |

After signing in, navigate directly to Lightsail via:
`https://lightsail.aws.amazon.com/ls/webapp/eu-central-1/instances`

### Amazon RDS PostgreSQL (Frankfurt Region)

| Field | Value |
|---|---|
| Host | `retail-radar-db.cbyyqyueehc2.eu-central-1.rds.amazonaws.com` |
| Port | `5432` |
| Database | `retail_radar` |
| Username | `retail_admin` |
| Password | `IbJZwWlG4FJJkFl49Loy` |
| SSL | Required (`sslmode=require`) |

Connection string:
```
postgresql://retail_admin:IbJZwWlG4FJJkFl49Loy@retail-radar-db.cbyyqyueehc2.eu-central-1.rds.amazonaws.com:5432/retail_radar?sslmode=require
```

Connect using any PostgreSQL client (DBeaver, pgAdmin, psql). The database is accessible from outside AWS — SSL is mandatory.

### Database Schemas and Tables

The database is named `retail_radar` and has four schemas:

#### `core` — Retail operations backbone

| Table | Purpose |
|---|---|
| `tenants` | One row per retailer account (multi-tenant root) |
| `stores` | Physical store locations belonging to a tenant |
| `app_users` | Login accounts (admin or shop role) |
| `user_memberships` | Maps users to tenants with owner/manager/staff roles |
| `auth_sessions` | Active login sessions and token hashes |
| `shop_profiles` | Business details: name, address, contact, onboarding status |
| `notifications` | In-app alerts sent to admin or shop users |
| `suppliers` | Supplier directory per tenant |
| `products` | Product catalog: brand, name, category, gender, season |
| `sku_variants` | Individual SKUs with size, color, cost price, reorder levels |
| `prices` | Retail and sale price history per SKU (current = `valid_to IS NULL`) |
| `inventory_balances` | Current stock quantity per SKU per store |
| `inventory_movements` | Audit log of every stock change (purchase, sale, adjustment, etc.) |
| `purchase_orders` | PO headers per supplier |
| `purchase_order_lines` | Line items per PO (quantities ordered vs received) |
| `sales_transactions` | Sale header records |
| `sales_transaction_lines` | Line items per sale (qty, price, cost, discount) |
| `financial_profiles` | One row per tenant: assets, liabilities, opex, projected revenue, runway |
| `audit_logs` | Full before/after state log for every entity change |

#### `intel` — Competitor intelligence

| Table | Purpose |
|---|---|
| `shops` | Known competitor shops (Adidas LB, Mike Sport, Tchooz, etc.) with Apify actor IDs |
| `tenant_competitors` | Which competitors each tenant is tracking |
| `competitor_requests` | Tenant requests to add a new competitor (pending/approved/rejected) |
| `scrape_runs` | One row per Apify scrape run with status and item count |
| `competitor_product_snapshots` | Full historical snapshot of every competitor product per run |
| `competitor_products_latest` | Deduplicated latest price/availability per competitor product (fast reads) |

#### `marketing` — Recommendations and campaigns

| Table | Purpose |
|---|---|
| `recommendations` | AI/rule-based decisions per SKU: HOLD / MARKDOWN / PROMOTE / CLEAR with confidence score |
| `system_decision_runs` | Batch run metadata (trigger, progress, status) |
| `system_decision_latest` | Latest live decision per SKU (primary read target for the dashboard) |
| `campaigns` | Campaign drafts and published posts linked to a recommendation |
| `tenant_social_accounts` | Connected social channels per tenant (Facebook, Instagram, TikTok, Telegram) |

#### `telegram` — Assistant bot

| Table | Purpose |
|---|---|
| `registration_codes` | One-time codes retailers use to bind their Telegram chat to their tenant |
| `conversations` | Active Telegram conversations per tenant+chat |
| `processed_messages` | Deduplication log to avoid processing the same message twice |

---

## What Was Implemented

Retail Radar AI includes these major capabilities:

| Area | Implemented capability |
|---|---|
| Authentication | Admin/shop login flow, JWT-style auth boundary, protected dashboard routes |
| Inventory | CSV import, SKU management, stock levels, retail/cost price tracking, reorder flags |
| Competitor intelligence | Apify-based competitor scraping, webhook ingestion, run tracking, latest competitor snapshots |
| Decision intelligence | Business rules, event proximity, markdown/promotion/clearance signals, CatBoost-backed recommendation path, SHAP-style explainability support |
| Campaign creative | Promotion/campaign copy generation, creative variants, social-ready messaging |
| Financial monitoring | Finance page and data surfaces for retail decision support |
| Social wiring | Social account/API endpoint wiring for campaign workflows |
| Radar Assistant | Browser assistant and Telegram assistant service connected to the EEP and campaign services |
| Observability | Prometheus and Grafana deployed inside Kubernetes |
| CI/CD | GitHub Actions test, image build, GHCR push, and production k3s deployment |
| Cloud deployment | AWS Lightsail load balancer, two k3s servers, RDS PostgreSQL, TLS domain |

## System Architecture

```
Production Architecture: 2 Lightsail Servers + Separate Webhook Server + Amazon RDS
─────────────────────────────────────────────────────────────────────────────────────

  Public User Entry                k3s Kubernetes Cluster on AWS Lightsail
  ─────────────────               ─────────────────────────────────────────────────────────
                                   Traefik Ingress + Path Routing
  Browser / Phone                  / → Frontend  |  /api → EEP  |  /ie1 → Market Intel
       │                           /ie2 → ML Decision  |  /ie3 → Campaign Creative
       ▼                          ┌───────────────────────────────────────────────────────┐
  Spaceship DNS                   │  SERVER 1 — rr-node-1          SERVER 2 — rr-node-2  │
  retailradar.site                │  4 GB RAM · 2 vCPU             4 GB RAM · 2 vCPU     │
       │                          │  k3s control-plane + etcd      k3s worker node        │
       ▼                          │  ┌──────────┬──────────┐      ┌──────────┬──────────┐ │
  AWS Lightsail Load Balancer ───▶│  │ Frontend │  EEP API │      │ Frontend │  EEP API │ │
  rr-lb (HTTPS + TLS cert)        │  ├──────────┼──────────┤      ├──────────┼──────────┤ │
                                  │  │ IE1 Mkt  │ IE2 ML   │      │ IE1 Mkt  │ IE2 ML   │ │
                                  │  │ Intel    │ Decision │      │ Intel    │ Decision │ │
  Separate Webhook Server         │  ├──────────┼──────────┤      ├──────────┼──────────┤ │
  ───────────────────────         │  │ IE3 Camp │PgBouncer │      │ IE3 Camp │PgBouncer │ │
  retail-radar-webhook            │  │ Creative │          │      │ Creative │          │ │
  2 GB RAM · Lightsail            │  └──────────┴──────────┘      └──────────┴──────────┘ │
  (NOT in k8s cluster)            └───────────────────────┬───────────────────────────────┘
       │                                                   │
  Apify Scrapers                                           │
  Webhook Server ─────────────────────────────────────────▼
  (receives Apify webhooks,                  Amazon RDS PostgreSQL
   writes competitor data                    retail-radar-db · Frankfurt
   directly to RDS)                          Stores: products, inventory,
                                             recommendations, competitor data,
                                             users, tenants, financial data
                                             ──────────────────────────────
                                             Access: via PgBouncer inside k8s
                                             pods → pgbouncer :6432 → RDS :5432
```

```mermaid
flowchart TB
    subgraph Public["Public Entry"]
        User["Browser / Phone"]
        DNS["Spaceship DNS\nretailradar.site"]
        LB["AWS Lightsail Load Balancer\nrr-lb · HTTPS + TLS"]
    end

    subgraph K8s["k3s Kubernetes Cluster — 2 × 4 GB Lightsail Servers"]
        direction TB
        Traefik["Traefik Ingress\n/ → Frontend | /api → EEP | /ie1 /ie2 /ie3"]
        subgraph N1["rr-node-1 (control-plane + worker)"]
            F1["Frontend"] 
            E1["EEP API"]
            M1["IE1 Market Intel"]
            D1["IE2 ML Decision"]
            C1["IE3 Campaign Creative"]
            PB1["PgBouncer"]
        end
        subgraph N2["rr-node-2 (worker)"]
            F2["Frontend"]
            E2["EEP API"]
            M2["IE1 Market Intel"]
            D2["IE2 ML Decision"]
            C2["IE3 Campaign Creative"]
            PB2["PgBouncer"]
        end
    end

    subgraph Webhook["Separate Webhook Server\nretail-radar-webhook · 2 GB Lightsail"]
        Apify["Apify Scrapers"]
        WH["Webhook Handler"]
    end

    subgraph DB["Amazon RDS PostgreSQL\neu-central-1 Frankfurt"]
        RDS[("retail_radar DB\ncore · intel · marketing · telegram")]
    end

    User --> DNS --> LB --> Traefik
    Traefik --> N1
    Traefik --> N2
    PB1 --> RDS
    PB2 --> RDS
    Apify --> WH --> RDS
```

## Cloud Resources

### AWS Lightsail Servers

The current AWS setup has three Lightsail server assets in the project history: one older webhook server and two active Kubernetes nodes. The production dashboard/API is served by the two k3s nodes.

| Server | Public IPv4 | Private IPv4 | Current role | Size |
|---|---:|---:|---|---|
| `retail-radar-webhook` / Box A | Verify in AWS Lightsail | Verify in AWS Lightsail | Legacy/optional 2 GB Apify webhook server from the earlier RDS webhook deployment | 2 GB class in the original plan |
| `rr-node-1` / Box B | `18.192.240.243` | `172.26.11.208` | Active k3s control-plane, etcd, and worker | 4 GB RAM, 2 vCPU, 80 GB SSD |
| `rr-node-2` / Box C | `18.185.239.195` | `172.26.7.42` | Active k3s worker | 4 GB RAM, 2 vCPU, 80 GB SSD |


### Why Two Servers Instead Of One

Two servers make the deployment stronger than a single VPS:

- The workload is split across two machines, so CPU and memory pressure is lower.
- Kubernetes can schedule replicas across nodes, which reduces the chance that one overloaded node takes the whole app down.
- If a worker pod dies, Kubernetes can recreate it.
- If one node becomes unavailable, some replicas can continue running on the other node, depending on which pods were scheduled there.
- The Lightsail load balancer can send traffic to both instances.

`rr-node-1` is still special because it hosts the k3s control plane and embedded etcd. This means the cluster is more resilient than one plain Docker host, but it is not a fully high-availability Kubernetes control plane. A true HA control plane would require three server/control-plane nodes.

### Amazon RDS PostgreSQL

The database is Amazon RDS PostgreSQL. Application pods do not store persistent production data locally. They connect to PostgreSQL through PgBouncer inside Kubernetes:

```text
Application pod -> pgbouncer.retail-radar.svc.cluster.local:6432 -> Amazon RDS PostgreSQL with SSL
```

Main database areas:

| Schema / area | Purpose |
|---|---|
| `core` | Tenants, stores, products, SKU variants, inventory balances, prices, suppliers, sales, audit logs |
| `intel` | Apify scrape runs, competitor product snapshots, latest competitor products |
| `marketing` | Recommendations, campaigns, promotion artifacts |
| auth/admin tables | Login, shop/admin identity, protected access |
| financial/social tables | Financial snapshots, social account wiring, campaign publishing support |

PgBouncer keeps database connections under control. This is important because Kubernetes may run many pods, and opening direct PostgreSQL connections from every pod can overload a small RDS instance.

### Domain, DNS, TLS, And Load Balancing

The public domain is managed in Spaceship:

| DNS name | Type | Target |
|---|---|---|
| `www.retailradar.site` | CNAME | Lightsail load balancer DNS |
| `retailradar.site` | Redirect or DNS target | Redirects/points to the production site |
| AWS validation CNAMEs | CNAME | AWS ACM certificate validation records |

The Lightsail load balancer `rr-lb` terminates HTTPS using the AWS certificate for:

- `retailradar.site`
- `www.retailradar.site`

Traffic path:

```text
Browser
  -> retailradar.site / www.retailradar.site
  -> Spaceship DNS
  -> AWS Lightsail load balancer rr-lb
  -> rr-node-1 or rr-node-2 on port 80
  -> lb-node-proxy DaemonSet
  -> Traefik NodePort 30080
  -> Kubernetes service and pod
```

The `lb-node-proxy` DaemonSet exists because the Lightsail load balancer forwards to instance port `80`, while k3s Traefik exposes HTTP through NodePort `30080`. The proxy binds host port `80` on each node and forwards traffic to Traefik.

## Kubernetes Deployment

Kubernetes manifests live in `infra/k8s/`.

| File | Purpose |
|---|---|
| `00-config.yaml` | Namespace, ConfigMaps, shared non-secret configuration |
| `10-pgbouncer.yaml` | PgBouncer deployment and service |
| `20-backends.yaml` | EEP, IE1, IE2, IE3 deployments/services and autoscaling |
| `30-frontend-telegram.yaml` | Frontend and Telegram/Radar Assistant deployments/services |
| `40-ingress.yaml` | Traefik ingress routing rules |
| `50-monitoring.yaml` | Prometheus and Grafana |
| `60-lb-node-proxy.yaml` | Node-level port 80 proxy for Lightsail LB |
| `kustomization.yaml` | Image tag pinning and full stack apply target |

Production namespace:

```text
retail-radar
```

Main Kubernetes services:

| Service | Port | Role |
|---|---:|---|
| `frontend` | 80 | React dashboard served by Nginx |
| `eep` | 8000 | Public API, orchestration, auth, inventory, Apify ingest |
| `ie1` | 8001 | Market/competitor intelligence API |
| `ie2` | 8002 | Decision intelligence API and model/rules engine |
| `ie3` | 8003 | Campaign creative API |
| `telegram` | 8004 | Radar Assistant and Telegram webhook service |
| `pgbouncer` | 6432 | PostgreSQL connection pool |
| `prometheus` | 9090 | Metrics collection |
| `grafana` | 3000 | Monitoring dashboards |

Traefik routes:

| Public path | Target service | Behavior |
|---|---|---|
| `/` | `frontend:80` | SPA dashboard |
| `/api/*` | `eep:8000` | Strips `/api` before forwarding |
| `/apify/*` | `eep:8000` | Apify/webhook route, no strip |
| `/webhooks/*` | `eep:8000` | Apify webhook route, no strip |
| `/assistant-api/*` | `telegram:8004` | Browser assistant API |
| `/webhook/telegram/*` | `telegram:8004` | Telegram webhook route |
| `/ie1/*` | `ie1:8001` | Market intelligence direct API |
| `/ie2/*` | `ie2:8002` | Decision intelligence direct API |
| `/ie3/*` | `ie3:8003` | Campaign creative direct API |

## EEP And IEP Responsibilities

The project follows an External Endpoint plus Internal Endpoint architecture.

### EEP - External Endpoint

Location: `eep/`

The EEP is the public API boundary and orchestration layer. It handles:

- Authentication and dashboard API calls.
- Inventory CRUD/import workflows.
- Recommendation orchestration.
- Apify webhook ingestion.
- RDS reads/writes through PgBouncer.
- Public health/metrics endpoints.
- Coordination with IE1, IE2, IE3, and the assistant service.

### IE1 - Market Intelligence

Location: `services/market_intelligence/`

IE1 focuses on competitor and market signals:

- Competitor price matching.
- Scraped data processing.
- Market intelligence endpoints.
- Signals consumed by the decision layer.

### IE2 - Decision Intelligence

Location: `services/decision_intelligence/`

IE2 is the decision engine:

- Rule engine for HOLD, MARKDOWN, PROMOTE, CLEAR.
- Event proximity and seasonality signals.
- CatBoost-backed recommendation support.
- Explainability output and model metrics.
- Horizontal Pod Autoscaler in Kubernetes, with multiple replicas.

### IE3 - Campaign Creative

Location: `services/campaign_creative/`

IE3 generates campaign support:

- Promotional copy.
- Creative variants.
- Campaign messaging.
- Social-ready outputs for products that should be promoted.

### Telegram / Radar Assistant

Location: `services/telegram_assistant/`

This service powers:

- Browser assistant at `/assistant`.
- Assistant API through `/assistant-api`.
- Telegram webhook integration through `/webhook/telegram`.
- EEP and IE3 calls for data-backed assistant responses.

It intentionally runs as a single active replica because bot/webhook services can duplicate messages if multiple instances process the same update.

## Apify Integration

Apify is used for competitor scraping. Scheduled Apify actor runs collect competitor data, then notify the deployed application through webhooks.

Flow:

```text
Apify scheduled actor
  -> actor run succeeds
  -> Apify sends webhook to Retail Radar
  -> EEP verifies webhook secret
  -> EEP fetches run/dataset data from Apify API
  -> EEP normalizes records
  -> EEP writes scrape run and product snapshots to RDS
  -> dashboard and IE services use updated competitor intelligence
```

Important EEP webhook paths:

```text
POST /webhooks/apify/run-succeeded?shop=SHOP_CODE
POST /apify/webhook?shop=SHOP_CODE
POST /webhooks/apify/replay-run?shop=SHOP_CODE&run_id=APIFY_RUN_ID
```

Security:

- Apify requests use `APIFY_WEBHOOK_SECRET`.
- EEP uses `APIFY_TOKEN` to fetch actor run/dataset data.
- Tokens are stored as secrets, not committed to git.

## CI/CD

CI/CD is implemented with GitHub Actions in `.github/workflows/deploy.yml`.

Trigger:

- Push to `dev`: run tests and build/push images.
- Push/merge to `main`: run tests, build/push images, then deploy to production k3s.
- Manual run: supported by `workflow_dispatch`.

Pipeline:

```mermaid
flowchart LR
    Push["Push to dev or main"] --> Test["Run Python tests and frontend build"]
    Test --> Build["Build Docker images"]
    Build --> GHCR["Push images to GHCR"]
    GHCR --> Gate{"Branch is main?"}
    Gate -- "No" --> Stop["Stop after build"]
    Gate -- "Yes" --> SCP["Copy k8s manifests to rr-node-1"]
    SCP --> Kustomize["Pin image tags to git short SHA"]
    Kustomize --> Apply["kubectl apply -k"]
    Apply --> Rollout["Wait for rollouts and health checks"]
```

Images pushed to GHCR:

```text
ghcr.io/mhmd-jawad/retail-radar-eep:<git-sha>
ghcr.io/mhmd-jawad/retail-radar-ie1:<git-sha>
ghcr.io/mhmd-jawad/retail-radar-ie2:<git-sha>
ghcr.io/mhmd-jawad/retail-radar-ie3:<git-sha>
ghcr.io/mhmd-jawad/retail-radar-frontend:<git-sha>
ghcr.io/mhmd-jawad/retail-radar-telegram:<git-sha>
```

Required GitHub Actions secrets:

| Secret | Purpose |
|---|---|
| `GHCR_TOKEN` | Push/pull private GHCR images |
| `BOX_B_HOST` | Public IP/host of the production k3s control-plane node |
| `BOX_B_USER` | SSH user, usually `ubuntu` |
| `BOX_B_SSH_KEY` | Private SSH key for CI deployment |
| `VITE_API_KEY` | Frontend build-time API key if required |
| `VITE_GRAFANA_URL` | Frontend Grafana link |

## Capacity And Scaling

The cluster has two Lightsail nodes, each with 2 vCPU and about 4 GB RAM. Kubernetes reports a theoretical pod limit of about 110 pods per node, or about 220 pods total. That number is a networking/scheduler maximum, not the practical application capacity.

Practical capacity is limited by RAM, CPU, model memory, and database connection limits. With the current services, the realistic target is approximately 25 to 35 application pods before resizing, depending on workload and traffic.

Current resource pattern:

- `rr-node-1` hosts the control plane plus worker pods.
- `rr-node-2` hosts worker pods.
- IE2 can run multiple replicas because it is the most important model-serving component.
- Telegram/Radar Assistant should remain a single active replica.
- PgBouncer runs multiple replicas to protect RDS from too many direct connections.
- Prometheus and Grafana are stateful monitoring services and should be treated carefully.

If production traffic grows, the next improvements are:

1. Move to larger Lightsail instances or EC2/EKS.
2. Add a third control-plane node for true control-plane HA.
3. Move monitoring to managed services or a larger node.
4. Increase RDS size and tune PgBouncer pool limits.
5. Add resource requests/limits based on observed Prometheus data.



## Repository Structure

```text
.
|-- .github/workflows/          GitHub Actions CI/CD
|-- apify/                      Apify actor/task related code
|-- catboost_info/              Model training/output metadata
|-- data/                       Local/sample data
|-- docs/                       Deployment, rubric, database, and architecture docs
|-- eep/                        External Endpoint FastAPI service
|-- frontend/                   React/Vite dashboard
|-- infra/
|   |-- k8s/                    Kubernetes production manifests
|   |-- monitoring/             Prometheus/Grafana configuration
|   `-- postgres/               PostgreSQL schema/migration SQL
|-- mlartifacts/                Model artifacts and evaluation outputs
|-- services/
|   |-- market_intelligence/    IE1
|   |-- decision_intelligence/  IE2
|   |-- campaign_creative/      IE3
|   `-- telegram_assistant/     Radar Assistant and Telegram service
|-- stylepulse/                 Shared/domain package code
|-- tests/                      Unit and integration tests
`-- README.md                   This file
```

## Security Model

The project uses several layers of security:

- HTTPS at the Lightsail load balancer.
- DNS validation through AWS certificate records.
- Kubernetes secrets for production credentials.
- GitHub Actions secrets for CI/CD credentials.
- PgBouncer between services and RDS.
- RDS access kept out of public browser traffic.
- Webhook secrets for Apify and Telegram.
- App authentication for dashboard users.

Known production-hardening recommendations:

- Rotate any credential that was ever pasted into a chat, screenshot, or terminal recording.
- Keep `.env`, `k8s.env`, `pgbouncer.env`, kubeconfigs, SSH keys, and tokens out of git.
- Use read-only credentials for professor/database inspection.
- Enable MFA on AWS and GitHub.
- Add stricter EEP rate limiting for public endpoints.
- Consider AWS WAF or CloudFront if public traffic grows.
- Move from two-node k3s to managed EKS or a three-control-plane design if this becomes a real production business.

## Key Tradeoffs

The main engineering tradeoffs are documented in `docs/TRADEOFFS.md`. Summary:

| Tradeoff | Choice made | Reason |
|---|---|---|
| Rule-gated model vs. pure ML | Rule-gated CatBoost path | Business safety and explainability are more important than unrestricted model autonomy |
| Heuristic labels vs. waiting for real outcomes | Start with heuristic labels | Allows a working system before long-term sales outcome data exists |
| In-process IE2 support vs. only service calls | Hybrid approach | Reduces latency and memory pressure on small Lightsail machines while keeping IE2 as its own service |
| Daily Apify batch vs. real-time scraping | Daily/scheduled Apify scraping | Predictable cost and lower scraping risk; freshness is surfaced through features |
| Two k3s nodes vs. one server | Two nodes | Better scheduling, capacity, and partial failure tolerance |

## Useful Documentation

- `docs/PRODUCTION_DEPLOYMENT_ARCHITECTURE.md` - detailed production architecture
- `docs/KUBERNETES_DEPLOYMENT.md` - step-by-step k3s deployment guide
- `docs/RUBRIC_COMPLIANCE_REVIEW.md` - project/rubric readiness review
- `docs/TRADEOFFS.md` - engineering tradeoffs
- `docs/rds-database-logic.md` - RDS schema and data logic
- `docs/aws-rds-apify-webhook.md` - Apify/RDS webhook runbook
- `docs/full-stack-docker-deployment.md` - Docker deployment reference

## License

This project is for academic and demonstration use unless a separate license file states otherwise.
