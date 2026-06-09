# StylePulse AI

> **AI-Powered Pricing & Promotion Intelligence for Adidas Single-Brand Retailers**

[![Tests](https://img.shields.io/badge/tests-pending-lightgrey)]()
[![License](https://img.shields.io/badge/license-MIT-blue)]()
[![Python](https://img.shields.io/badge/python-3.11-blue)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green)]()

StylePulse AI is a multi-service decision-support system that monitors competitor prices daily, tracks inventory performance, understands Adidas seasonal patterns, and recommends exactly what to do with each product every week â€” **HOLD**, **MARKDOWN**, **PROMOTE**, or **CLEAR** â€” with every decision explained in plain English and requiring explicit human approval.

---

## The Problem

A small Adidas retailer manages 150â€“500 products. Every week they must decide: Is this product priced correctly? Should I discount it? They have no idea what competitors are charging for the same item today. They don't know Black Friday is 3 weeks away and they should HOLD prices. They spend 4â€“6 hours per week on these decisions and get them wrong 40% of the time. Wrong decisions cost **$15,000â€“60,000 per year**.

## The Solution

StylePulse AI replaces manual guesswork with an automated weekly intelligence system:

| What it does | How |
|---|---|
| Track competitor prices daily | Nightly scraper â†’ `competitor_prices` table |
| Understand seasonal patterns | Adidas calendar engine with category-specific scores |
| Recommend the right action | CatBoost ML model + 5 hard business rules |
| Write campaign copy automatically | Claude API generates Instagram/Facebook/WhatsApp copy |
| Explain every decision | SHAP values translated to plain English |
| Require human approval | Every recommendation must be approved before action |

---

## Architecture

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                        MERCHANT                                  â”‚
â”‚                    (Dashboard / API)                              â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                       â”‚
                       â–¼
              â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
              â”‚  EEP (port 8000) â”‚  â† Orchestrator: auth, rate limit,
              â”‚  External        â”‚     circuit breakers, confidence decay
              â”‚  Endpoint        â”‚
              â””â”€â”€â”€â”¬â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”¬â”€â”€â”˜
                  â”‚    â”‚    â”‚
          â”Œâ”€â”€â”€â”€â”€â”€â”€â”˜    â”‚    â””â”€â”€â”€â”€â”€â”€â”€â”€â”
          â–¼            â–¼             â–¼
   â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â” â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â” â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
   â”‚ IE1 (8001) â”‚ â”‚ IE2 (8002)  â”‚ â”‚  IE3 (8003)    â”‚
   â”‚ Market     â”‚ â”‚ Decision    â”‚ â”‚  Campaign       â”‚
   â”‚ Intelligenceâ”‚ â”‚ Intelligenceâ”‚ â”‚  Creative       â”‚
   â”‚            â”‚ â”‚             â”‚ â”‚  (only if       â”‚
   â”‚ Competitor â”‚ â”‚ Hard Rules  â”‚ â”‚   PROMOTE)      â”‚
   â”‚ signals,   â”‚ â”‚ + CatBoost  â”‚ â”‚                 â”‚
   â”‚ seasonalityâ”‚ â”‚ + SHAP      â”‚ â”‚  Claude API     â”‚
   â””â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”˜ â””â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”˜ â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
          â”‚              â”‚
          â–¼              â–¼
   â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
   â”‚       PostgreSQL             â”‚
   â”‚  8 tables: products,        â”‚
   â”‚  inventory, sales, traffic, â”‚
   â”‚  competitor_prices, features,â”‚
   â”‚  recommendations, campaigns â”‚
   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

---

## The 4 Decisions

| Decision | Badge | Meaning | When It Fires |
|---|---|---|---|
| **HOLD** | ðŸ”˜ Grey | Keep current price | Selling well, stock healthy, competitively priced |
| **MARKDOWN** | ðŸŸ  Orange | Reduce price | Competitor cheaper, product aging, season ending |
| **PROMOTE** | ðŸŸ¢ Green | Run marketing campaign | Season perfect, stock healthy, demand rising |
| **CLEAR** | ðŸ”´ Red | Sell at any price | 90+ days unsold, season over, dead stock |

---

## Local Development (How to Run)

This section documents the **current local dev setup** â€” three processes run side-by-side without Docker.

### Prerequisites

- Python 3.11+ with a virtual env at `../.venv` (one level above the repo root)
- Node.js 18+ **or** Bun â€” use `npx vite` if Bun is not installed
- AWS RDS reachable (credentials in `.env` at repo root and `services/campaign_creative/.env`)

### Required environment files

**`retail-radar-ai/.env`** (repo root)
```env
DATABASE_URL=postgresql://retail_admin:<password>@retail-radar-db.<region>.rds.amazonaws.com:5432/retail_radar?sslmode=require
```

**`retail-radar-ai/frontend/.env.local`**
```env
VITE_API_BASE_URL=http://localhost:8000
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

### Terminal 1 â€” EEP backend (port 8000)

```powershell
cd "c:\path\to\Radar Ai"
.venv\Scripts\Activate.ps1
cd retail-radar-ai
uvicorn eep.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify: `curl http://localhost:8000/health`

### Terminal 2 â€” IE3 Campaign Creative service (port 8003)

```powershell
cd "c:\path\to\Radar Ai"
.venv\Scripts\Activate.ps1
cd retail-radar-ai
uvicorn services.campaign_creative.main:app --host 0.0.0.0 --port 8003 --reload
```

Verify: `curl http://localhost:8003/health`

### Terminal 3 â€” React frontend (port 8082)

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
| `http://localhost:8000/report/live` | Live report JSON from RDS (inventory + promotion decisions) |
| `http://localhost:8000/report` | Static report JSON |
| `http://localhost:8000/docs` | FastAPI Swagger UI |
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

### 2. Start the Docker App Stack

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

This starts EEP (8000), IE1 (8001), IE2 (8002), IE3 (8003), the dashboard (4173), Prometheus (9090), Grafana (3001), and uses `DATABASE_URL` from the repo root `.env`.

Local PostgreSQL and Adminer are optional now. Start them only when your `.env` points to a local database:

```bash
docker compose -f infra/docker-compose.yml --profile local-db up -d postgres adminer
```

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
| `POST` | `/inventory/import` | Save validated inventory rows to PostgreSQL |
| `GET` | `/recommendations` | List all pending recommendations |
| `GET` | `/status/{sku_id}` | Get recommendation with confidence decay |
| `POST` | `/recommendations/{sku_id}/review` | **Human Validation** — accept / override / reject the system recommendation |
| `GET` | `/recommendations/reviews` | List human reviews (ground-truth labels) |
| `GET` | `/analytics/recommendation-reviews` | Acceptance / override / agreement rates + trend |
| `GET` | `/admin/export/training-labels` | Export human-labeled retraining dataset (JSONL) |
| `GET` | `/health` | Service health check |
| `GET` | `/metrics` | Prometheus metrics |

> **Human Validation Layer** — a final human-review stage that captures accept/override/reject
> decisions as ground-truth labels for retraining, with full auditability and analytics, without
> ever modifying the system recommendation. See [docs/HUMAN_VALIDATION_LAYER.md](./docs/HUMAN_VALIDATION_LAYER.md).

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
â”œâ”€â”€ services/
â”‚   â”œâ”€â”€ eep/                    # Orchestrator (port 8000)
â”‚   â”œâ”€â”€ market_intelligence/    # IE1 â€” Competitor signals (port 8001)
â”‚   â”œâ”€â”€ decision_intelligence/  # IE2 â€” ML + Rules (port 8002)
â”‚   â”œâ”€â”€ campaign_creative/      # IE3 â€” LLM copy gen (port 8003)
â”‚   â””â”€â”€ shared/                 # Database models, metrics
â”œâ”€â”€ ml_pipeline/
â”‚   â”œâ”€â”€ features/               # Feature engineering + validation
â”‚   â”œâ”€â”€ training/               # CatBoost + baseline training
â”‚   â””â”€â”€ evaluation/             # Model comparison + promotion
â”œâ”€â”€ dashboard/                  # React frontend
â”œâ”€â”€ data/
â”‚   â”œâ”€â”€ synthetic/              # Generated training data
â”‚   â””â”€â”€ scripts/                # Data gen + DB seeding
â”œâ”€â”€ infra/
â”‚   â”œâ”€â”€ k8s/                    # Kubernetes manifests
â”‚   â””â”€â”€ monitoring/             # Prometheus + Grafana configs
â”œâ”€â”€ tests/
â”‚   â”œâ”€â”€ unit/
â”‚   â”œâ”€â”€ integration/
â”‚   â”‚   â””â”€â”€ golden/             # 6 mandatory golden scenarios
â”‚   â””â”€â”€ e2e/
â”œâ”€â”€ docs/
â”‚   â”œâ”€â”€ technical/
â”‚   â”œâ”€â”€ business/
â”‚   â””â”€â”€ mlops/
â”œâ”€â”€ docker-compose.yml
â”œâ”€â”€ Makefile
â”œâ”€â”€ PLAN.md
â””â”€â”€ CHANGELOG.md
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
| **1. Foundation** | 1â€“3 | Repo, DB schema, synthetic data, all services return `/health` |
| **2. Core Services** | 4â€“8 | IE1 + IE2 + IE3 fully working, ML model trained in MLflow |
| **3. Integration + Dashboard** | 9â€“11 | EEP orchestration, 6 golden tests, React dashboard |
| **4. Infra + Polish** | 12â€“13 | Docker Compose full stack, K8s manifests, Prometheus + Grafana, CI/CD |
| **5. Docs + Deploy + Demo** | 14â€“15 | Cloud deploy, all docs, demo rehearsal, submission |

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
| 1 | Dead stock (150 days, 8% sell-through) | â†’ CLEAR |
| 2 | Low margin (12%, below 15% floor) | â†’ NOT MARKDOWN |
| 3 | Low stock (8 units) | â†’ HOLD only |
| 4 | Recent discount (14 days ago) | â†’ NOT MARKDOWN |
| 5 | PROMOTE decision | â†’ Campaign creative generated |
| 6 | Stale competitor data (36h old) | â†’ Confidence degraded |

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

- **Prometheus:** http://localhost:9090 â€” service metrics
- **Grafana:** http://localhost:3001 â€” observability dashboard
- **MLflow:** http://localhost:5000 â€” experiment tracking, model registry

See [Prometheus and Grafana Monitoring](./docs/monitoring-prometheus-grafana.md) for the current EEP monitoring setup.

---

## Environment Variables

```env
# Database
DATABASE_URL=postgresql+asyncpg://stylepulse:stylepulse@localhost:5432/stylepulse

# Service URLs (for EEP â†’ IE1/IE2/IE3 communication)
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

*StylePulse AI â€” Team: Hassan Fouani Â· Mohammad Jawad Â· Mohammad Farhat*
