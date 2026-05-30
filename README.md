# StylePulse AI

> **AI-Powered Pricing & Promotion Intelligence for Adidas Single-Brand Retailers**

[![Tests](https://img.shields.io/badge/tests-pending-lightgrey)]()
[![License](https://img.shields.io/badge/license-MIT-blue)]()
[![Python](https://img.shields.io/badge/python-3.11-blue)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green)]()

StylePulse AI is a multi-service decision-support system that monitors competitor prices daily, tracks inventory performance, understands Adidas seasonal patterns, and recommends exactly what to do with each product every week — **HOLD**, **MARKDOWN**, **PROMOTE**, or **CLEAR** — with every decision explained in plain English and requiring explicit human approval.

---

## The Problem

A small Adidas retailer manages 150–500 products. Every week they must decide: Is this product priced correctly? Should I discount it? They have no idea what competitors are charging for the same item today. They don't know Black Friday is 3 weeks away and they should HOLD prices. They spend 4–6 hours per week on these decisions and get them wrong 40% of the time. Wrong decisions cost **$15,000–60,000 per year**.

## The Solution

StylePulse AI replaces manual guesswork with an automated weekly intelligence system:

| What it does | How |
|---|---|
| Track competitor prices daily | Nightly scraper → `competitor_prices` table |
| Understand seasonal patterns | Adidas calendar engine with category-specific scores |
| Recommend the right action | CatBoost ML model + 5 hard business rules |
| Write campaign copy automatically | Claude API generates Instagram/Facebook/WhatsApp copy |
| Explain every decision | SHAP values translated to plain English |
| Require human approval | Every recommendation must be approved before action |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MERCHANT                                  │
│                    (Dashboard / API)                              │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
              ┌────────────────┐
              │  EEP (port 8000) │  ← Orchestrator: auth, rate limit,
              │  External        │     circuit breakers, confidence decay
              │  Endpoint        │
              └───┬────┬────┬──┘
                  │    │    │
          ┌───────┘    │    └────────┐
          ▼            ▼             ▼
   ┌────────────┐ ┌─────────────┐ ┌────────────────┐
   │ IE1 (8001) │ │ IE2 (8002)  │ │  IE3 (8003)    │
   │ Market     │ │ Decision    │ │  Campaign       │
   │ Intelligence│ │ Intelligence│ │  Creative       │
   │            │ │             │ │  (only if       │
   │ Competitor │ │ Hard Rules  │ │   PROMOTE)      │
   │ signals,   │ │ + CatBoost  │ │                 │
   │ seasonality│ │ + SHAP      │ │  Claude API     │
   └──────┬─────┘ └──────┬──────┘ └────────────────┘
          │              │
          ▼              ▼
   ┌─────────────────────────────┐
   │       PostgreSQL             │
   │  8 tables: products,        │
   │  inventory, sales, traffic, │
   │  competitor_prices, features,│
   │  recommendations, campaigns │
   └─────────────────────────────┘
```

---

## The 4 Decisions

| Decision | Badge | Meaning | When It Fires |
|---|---|---|---|
| **HOLD** | 🔘 Grey | Keep current price | Selling well, stock healthy, competitively priced |
| **MARKDOWN** | 🟠 Orange | Reduce price | Competitor cheaper, product aging, season ending |
| **PROMOTE** | 🟢 Green | Run marketing campaign | Season perfect, stock healthy, demand rising |
| **CLEAR** | 🔴 Red | Sell at any price | 90+ days unsold, season over, dead stock |

---

## Local Development (How to Run)

This section documents the **current local dev setup** — three processes run side-by-side without Docker.

### Prerequisites

- Python 3.11+ with a virtual env at `../.venv` (one level above the repo root)
- Node.js 18+ **or** Bun — use `npx vite` if Bun is not installed
- AWS RDS reachable (credentials in `.env` at repo root and `services/campaign_creative/.env`)

### Required environment files

**`retail-radar-ai/.env`** (repo root)
```env
DATABASE_URL=postgresql://retail_admin:<password>@retail-radar-db.<region>.rds.amazonaws.com:5432/retail_radar?sslmode=require
```

**`retail-radar-ai/frontend/.env.local`**
```env
VITE_API_BASE_URL=http://localhost:8004
VITE_DATA_MODE=eep-live
VITE_IE3_BASE_URL=http://localhost:8003
```

**`retail-radar-ai/services/campaign_creative/.env`**
```env
DATABASE_URL=postgresql://retail_admin:<password>@retail-radar-db.<region>.rds.amazonaws.com:5432/retail_radar?sslmode=require
OPENROUTER_API_KEY=<your-openrouter-key>
GEMINI_API_KEY=<your-gemini-key>
FB_PAGE_ACCESS_TOKEN=<token>
FB_PAGE_ID=<id>
IG_USER_ID=<id>
IG_ACCESS_TOKEN=<token>
IMGBB_API_KEY=<key>
```

### Terminal 1 — EEP backend (port 8004)

```powershell
cd "c:\path\to\Radar Ai"
.venv\Scripts\Activate.ps1
cd retail-radar-ai
uvicorn eep.main:app --host 0.0.0.0 --port 8004 --reload
```

Verify: `curl http://localhost:8004/health`

### Terminal 2 — IE3 Campaign Creative service (port 8003)

```powershell
cd "c:\path\to\Radar Ai"
.venv\Scripts\Activate.ps1
cd retail-radar-ai
uvicorn services.campaign_creative.main:app --host 0.0.0.0 --port 8003 --reload
```

Verify: `curl http://localhost:8003/health`

### Terminal 3 — React frontend (port 8082)

```powershell
cd "c:\path\to\Radar Ai\retail-radar-ai\frontend"
npx vite --port 8082
```

> If port 8082 is already in use Vite auto-increments to 8083, etc.

Open: http://localhost:8082

### Key endpoints

| URL | What it shows |
|---|---|
| `http://localhost:8082/inventory` | Inventory management + Health analytics (live DB) |
| `http://localhost:8082/promotions` | Promote / Markdown / Clearance / Hold decisions (live DB) |
| `http://localhost:8082/financial` | Financial hub — Balance Sheet, Profitability, Cashflow, Lollar |
| `http://localhost:8004/report/live` | Live report JSON from RDS (inventory + promotion decisions) |
| `http://localhost:8004/report` | Static report JSON (financial pages) |
| `http://localhost:8004/docs` | FastAPI Swagger UI |
| `http://localhost:8003/docs` | IE3 campaign service Swagger UI |

---

## Quick Start (Docker)

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Node.js 18+ (for dashboard)
- Git

### 1. Clone & Configure

```bash
git clone https://github.com/your-team/stylepulse-ai.git
cd stylepulse-ai
cp .env.example .env
# Edit .env with your API keys
```

### 2. Start the Full Stack Locally

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

This starts EEP (8000), IE1 (8001), IE2 (8002), IE3 (8003), the dashboard (4173), PostgreSQL (5432), Adminer (8080), Prometheus (9090), and Grafana (3001).

For the Lightsail/RDS deployment flow, see `docs/full-stack-docker-deployment.md`.

### 3. Seed the Database

```bash
# Generate synthetic data
python data/scripts/generate_synthetic.py

# Load into PostgreSQL
python data/scripts/seed_database.py
```

### 4. Train the ML Model

```bash
python -m ml_pipeline.features.engineer
python -m ml_pipeline.training.train
python -m ml_pipeline.evaluation.promote
```

### 5. Verify

```bash
# Health checks
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health

# API docs
open http://localhost:8000/docs

# MLflow dashboard
open http://localhost:5000

# Grafana
open http://localhost:3001
```

### 6. Run Tests

```bash
# All tests
pytest tests/ -v

# Golden scenarios only
pytest tests/integration/golden/ -v

# With coverage
pytest tests/ --cov=services --cov-report=html
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/recommend/{sku_id}` | Get recommendation for a single SKU |
| `POST` | `/recommend/batch` | Up to 50 SKUs in one call |
| `POST` | `/upload/csv` | Upload product CSV for batch processing |
| `GET` | `/recommendations` | List all pending recommendations |
| `GET` | `/status/{sku_id}` | Get recommendation with confidence decay |
| `PATCH` | `/review/{sku_id}` | Approve / Edit / Reject / Snooze |
| `GET` | `/health` | Service health check |
| `GET` | `/metrics` | Prometheus metrics |

### Example: Get a Recommendation

```bash
curl -X POST http://localhost:8000/recommend/SKU-001 \
  -H "X-API-Key: dev-key-123" \
  -H "Content-Type: application/json"
```

Response:
```json
{
  "sku_id": "SKU-001",
  "product_name": "Adidas Ultraboost 23",
  "recommendation": "MARKDOWN",
  "confidence": 0.74,
  "effective_confidence": 0.71,
  "explanation": "You are 12% more expensive than JD Sports. Sales slowed 49% vs last month. 3 competitors are discounting this product.",
  "requires_human_approval": true,
  "campaign_creative": null,
  "suggested_price": 152.00,
  "margin_after_action": 0.25
}
```

---

## Project Structure

```
stylepulse-ai/
├── services/
│   ├── eep/                    # Orchestrator (port 8000)
│   ├── market_intelligence/    # IE1 — Competitor signals (port 8001)
│   ├── decision_intelligence/  # IE2 — ML + Rules (port 8002)
│   ├── campaign_creative/      # IE3 — LLM copy gen (port 8003)
│   └── shared/                 # Database models, metrics
├── ml_pipeline/
│   ├── features/               # Feature engineering + validation
│   ├── training/               # CatBoost + baseline training
│   └── evaluation/             # Model comparison + promotion
├── dashboard/                  # React frontend
├── data/
│   ├── synthetic/              # Generated training data
│   └── scripts/                # Data gen + DB seeding
├── infra/
│   ├── k8s/                    # Kubernetes manifests
│   └── monitoring/             # Prometheus + Grafana configs
├── tests/
│   ├── unit/
│   ├── integration/
│   │   └── golden/             # 6 mandatory golden scenarios
│   └── e2e/
├── docs/
│   ├── technical/
│   ├── business/
│   └── mlops/
├── docker-compose.yml
├── Makefile
├── PLAN.md
└── CHANGELOG.md
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2 |
| Database | PostgreSQL 16, SQLAlchemy 2.0, Alembic |
| ML | CatBoost, SHAP, MLflow, pandas, pandera |
| LLM | Anthropic Claude API |
| Frontend | React 18, TypeScript, Tailwind CSS, Vite |
| Infrastructure | Docker, Docker Compose, Kubernetes, Minikube |
| Monitoring | Prometheus, Grafana |
| CI/CD | GitHub Actions |
| Cloud | Railway.app / Render.com |

---

## 15-Day Timeline

| Phase | Days | What Gets Done |
|---|---|---|
| **1. Foundation** | 1–3 | Repo, DB schema, synthetic data, all services return `/health` |
| **2. Core Services** | 4–8 | IE1 + IE2 + IE3 fully working, ML model trained in MLflow |
| **3. Integration + Dashboard** | 9–11 | EEP orchestration, 6 golden tests, React dashboard |
| **4. Infra + Polish** | 12–13 | Docker Compose full stack, K8s manifests, Prometheus + Grafana, CI/CD |
| **5. Docs + Deploy + Demo** | 14–15 | Cloud deploy, all docs, demo rehearsal, submission |

> See [PLAN.md](./PLAN.md) for the full breakdown with daily task checklists.

---

## Team

| Member | Primary Ownership |
|---|---|
| **Hassan Fouani** | IE2 (Decision Intelligence), ML Pipeline, Synthetic Data |
| **Mohammad Jawad** | IE1 (Market Intelligence), IE3 (Campaign Creative) |
| **Mohammad Farhat** | EEP (Orchestrator), Dashboard, Infrastructure, Deployment |

---

## Testing

### Golden Scenarios (must always pass)

| # | Scenario | Expected |
|---|---|---|
| 1 | Dead stock (150 days, 8% sell-through) | → CLEAR |
| 2 | Low margin (12%, below 15% floor) | → NOT MARKDOWN |
| 3 | Low stock (8 units) | → HOLD only |
| 4 | Recent discount (14 days ago) | → NOT MARKDOWN |
| 5 | PROMOTE decision | → Campaign creative generated |
| 6 | Stale competitor data (36h old) | → Confidence degraded |

### Test Counts

| Layer | Target |
|---|---|
| Unit tests | 60+ |
| Integration tests | 15+ |
| Golden scenarios | 6 |
| E2E tests | 5+ |
| **Total** | **80+** |

---

## Monitoring

- **Prometheus:** http://localhost:9090 — service metrics
- **Grafana:** http://localhost:3001 — observability dashboard
- **MLflow:** http://localhost:5000 — experiment tracking, model registry

See [Prometheus and Grafana Monitoring](./docs/monitoring-prometheus-grafana.md) for the current EEP monitoring setup.

---

## Environment Variables

```env
# Database
DATABASE_URL=postgresql+asyncpg://stylepulse:stylepulse@localhost:5432/stylepulse

# Service URLs (for EEP → IE1/IE2/IE3 communication)
IE1_URL=http://localhost:8001
IE2_URL=http://localhost:8002
IE3_URL=http://localhost:8003

# API Keys
API_KEY=dev-key-123
APIFY_TOKEN=your-apify-token
ANTHROPIC_API_KEY=your-anthropic-key

# MLflow
MLFLOW_TRACKING_URI=http://localhost:5000
```

---

## License

MIT

---

*StylePulse AI — Team: Hassan Fouani · Mohammad Jawad · Mohammad Farhat*
