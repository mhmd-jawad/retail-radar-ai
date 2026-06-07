# StylePulse AI — Master Execution Plan

> **Team:** Hassan Fouani · Mohammad Jawad · Mohammad Farhat
> **Duration:** 15 days (April 7 – April 21, 2026)
> **Goal:** Deliver the full StylePulse AI system — 4 microservices, ML pipeline, dashboard, monitoring, deployment, docs, and demo-ready.

---

## Table of Contents

1. [Project Summary](#1-project-summary)
2. [Technology Stack](#2-technology-stack)
3. [Repository Structure](#3-repository-structure)
4. [Team Roles & Responsibilities](#4-team-roles--responsibilities)
5. [Phase Breakdown (15 Days)](#5-phase-breakdown-15-days)
6. [Detailed Task Checklists](#6-detailed-task-checklists)
7. [Synthetic Data Strategy](#7-synthetic-data-strategy)
8. [ML Pipeline Checklist](#8-ml-pipeline-checklist)
9. [API Contracts Quick Reference](#9-api-contracts-quick-reference)
10. [Infrastructure & Deployment Plan](#10-infrastructure--deployment-plan)
11. [Testing Plan](#11-testing-plan)
12. [Risk Register & Mitigations](#12-risk-register--mitigations)
13. [Daily Standup Protocol](#13-daily-standup-protocol)
14. [Definition of Done](#14-definition-of-done)

---

## 1. Project Summary

StylePulse AI is a **4-service microservice system** that:

- **IE1 (Market Intelligence):** Reads nightly-scraped competitor prices from a database, computes price-gap signals, seasonality scores, and confidence ratings.
- **IE2 (Decision Intelligence):** Runs 5 hard business rules + a CatBoost ML model to produce HOLD / MARKDOWN / PROMOTE / CLEAR recommendations with SHAP explanations.
- **IE3 (Campaign Creative):** When IE2 says PROMOTE, calls Claude API to generate Instagram/Facebook/WhatsApp campaign copy.
- **EEP (Orchestrator):** The single public endpoint. Receives requests, coordinates IE1→IE2→IE3, applies circuit breakers, confidence decay, and returns a `RecommendationPackage` requiring human approval.

A **React dashboard** lets the shop owner review, approve/edit/reject every recommendation. Everything is containerized (Docker Compose + Kubernetes manifests), monitored (Prometheus + Grafana), and ML-tracked (MLflow).

> **What already exists:** The `scraping/` folder contains a working proof-of-concept for scraping MikeSport Lebanon and Adidas Lebanon. It validated the style-code matching idea. **Do NOT copy its code into the final project.** Use it only as a reference for how HTML parsing and style-code extraction work. The final project starts fresh with a clean repo structure.

---

## 2. Technology Stack

### Backend (all services)

| Layer | Technology | Why |
|---|---|---|
| Language | **Python 3.11** | Team familiarity, ML ecosystem, FastAPI |
| API Framework | **FastAPI** | Async, auto-docs (/docs), Pydantic validation |
| Data Validation | **Pydantic v2** | Strict schemas for all request/response models |
| Database | **PostgreSQL 16** | Relational, mature, free, works with SQLAlchemy |
| ORM / Query | **SQLAlchemy 2.0** + **Alembic** | Async support, migrations |
| HTTP Client | **httpx** | Async HTTP calls between services |
| Task Scheduling | **APScheduler** or **cron in Docker** | Nightly scraper job |
| Scraping | **httpx + BeautifulSoup4 + lxml** (MVP), **Apify API** (production) | Already proven in prototype |
| Testing | **pytest** + **pytest-asyncio** + **httpx** (test client) | Standard Python testing |

### ML Pipeline

| Layer | Technology | Why |
|---|---|---|
| ML Model | **CatBoost** | Handles categorical features natively, SHAP support, fast training |
| Explainability | **SHAP** (TreeExplainer) | Required for plain-English explanations |
| Experiment Tracking | **MLflow** | Logs params, metrics, artifacts, model registry |
| Feature Validation | **pandera** | Schema enforcement on feature DataFrames |
| Data Processing | **pandas** + **numpy** | Feature engineering |

### Campaign Creative (IE3)

| Layer | Technology | Why |
|---|---|---|
| LLM Provider | **Anthropic Claude API** (claude-3-haiku or claude-3-sonnet) | Cost-effective, good at structured JSON output |
| SDK | **anthropic** Python package | Official SDK |
| Fallback | **Jinja2 templates** | When LLM fails twice, use safe template |

### Frontend (Dashboard)

| Layer | Technology | Why |
|---|---|---|
| Framework | **React 18** + **TypeScript** | Industry standard, team can learn fast |
| Styling | **Tailwind CSS** | Rapid UI without writing custom CSS |
| HTTP | **axios** or **fetch** | API calls to EEP |
| Charts | **Recharts** or **Chart.js** | SHAP bar chart, price history, margin simulator |
| Build Tool | **Vite** | Fast dev server, simple config |

> **Alternative (if React is too slow to learn):** Use **Streamlit** for the dashboard. It is Python-only, no JS needed, and can be deployed as a Docker container. Tradeoff: less polished UI but much faster to build.

### Infrastructure

| Layer | Technology | Why |
|---|---|---|
| Containerization | **Docker** + **Docker Compose** | All services + Postgres + MLflow + monitoring in one command |
| Orchestration | **Kubernetes manifests** (for submission) + **Minikube** (local demo) | Course requirement |
| Monitoring | **Prometheus** + **Grafana** | Metrics collection + dashboards |
| CI/CD | **GitHub Actions** | Auto-test on push, build Docker images |
| Cloud Deploy | **Railway.app** or **Render.com** (free tier) | Demo day deployment |

---

## 3. Repository Structure

Start with this exact folder structure from Day 1. Create every directory and `__init__.py` stub immediately.

```
stylepulse-ai/
│
├── README.md
├── PLAN.md
├── CHANGELOG.md
├── .gitignore
├── .env.example
├── docker-compose.yml
├── Makefile                          # shortcut commands
│
├── services/
│   ├── eep/                          # EEP — Orchestrator (port 8000)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py                   # FastAPI app, CORS, lifespan
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── recommend.py          # POST /recommend/{sku_id}, /recommend/batch
│   │   │   ├── inventory.py          # POST /inventory/import, inventory CRUD
│   │   │   ├── review.py             # PATCH /review/{sku_id}, GET /recommendations
│   │   │   ├── status.py             # GET /status/{sku_id}
│   │   │   └── health.py             # GET /health, /metrics
│   │   ├── orchestrator.py           # Coordinates IE1→IE2→IE3 calls
│   │   ├── circuit_breaker.py        # Circuit breaker per service
│   │   ├── confidence_decay.py       # Decay formula
│   │   ├── schemas.py                # RecommendationPackage, all shared Pydantic models
│   │   ├── config.py                 # Settings from env vars
│   │   ├── middleware.py             # API key auth, rate limiting
│   │   └── tests/
│   │       ├── test_orchestrator.py
│   │       ├── test_circuit_breaker.py
│   │       ├── test_confidence_decay.py
│   │       └── test_routes.py
│   │
│   ├── market_intelligence/          # IE1 — Market Intelligence (port 8001)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py                   # FastAPI app
│   │   ├── routes.py                 # POST /analyze
│   │   ├── service.py                # Core logic: read DB, compute signals
│   │   ├── seasonality.py            # Seasonality alignment scores
│   │   ├── calendar_events.py        # Calendar event proximity
│   │   ├── confidence.py             # 3-tier confidence scoring
│   │   ├── schemas.py                # CompetitorAnalysisRequest, CompetitorSignals
│   │   ├── config.py
│   │   ├── scraper/                  # Background nightly scraper
│   │   │   ├── __init__.py
│   │   │   ├── runner.py             # Nightly job entry point
│   │   │   ├── apify_client.py       # Apify API integration
│   │   │   ├── parsers.py            # HTML/JSON response parsing
│   │   │   └── storage.py            # Write to competitor_prices table
│   │   └── tests/
│   │       ├── test_service.py
│   │       ├── test_seasonality.py
│   │       ├── test_confidence.py
│   │       └── test_calendar.py
│   │
│   ├── decision_intelligence/        # IE2 — Decision Intelligence (port 8002)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py
│   │   ├── routes.py                 # POST /recommend
│   │   ├── rules_engine.py           # 5 hard rules
│   │   ├── feature_loader.py         # Load features from DB/CSV
│   │   ├── model_inference.py        # CatBoost predict + SHAP
│   │   ├── explainer.py              # SHAP → plain English translation
│   │   ├── reconciliation.py         # Merge rules + model output
│   │   ├── schemas.py                # RecommendationResult, SHAPFeature
│   │   ├── config.py
│   │   └── tests/
│   │       ├── test_rules_engine.py
│   │       ├── test_model_inference.py
│   │       ├── test_explainer.py
│   │       └── test_reconciliation.py
│   │
│   ├── campaign_creative/            # IE3 — Campaign Creative (port 8003)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py
│   │   ├── routes.py                 # POST /generate
│   │   ├── generator.py             # Claude API call + retry logic
│   │   ├── validator.py             # Schema validation on LLM output
│   │   ├── templates/               # Jinja2 fallback templates
│   │   │   ├── running_shoes.j2
│   │   │   ├── football_boots.j2
│   │   │   ├── lifestyle.j2
│   │   │   └── generic.j2
│   │   ├── prompt_versions.json     # Prompt version tracking
│   │   ├── schemas.py               # PromotionBrief, CampaignPackage
│   │   ├── config.py
│   │   └── tests/
│   │       ├── test_generator.py
│   │       ├── test_validator.py
│   │       └── test_templates.py
│   │
│   └── shared/                       # Shared utilities across services
│       ├── __init__.py
│       ├── database.py               # SQLAlchemy engine, session factory
│       ├── models.py                 # ORM models for all 8 tables
│       └── metrics.py                # Prometheus instrumentation helpers
│
├── ml_pipeline/
│   ├── features/
│   │   ├── engineer.py               # Compute 32 features from raw tables
│   │   └── validate.py               # pandera schema checks
│   ├── training/
│   │   ├── train.py                  # CatBoost training + MLflow logging
│   │   ├── baseline.py              # Simple rule-based baseline
│   │   └── hyperparams.py           # Hyperparameter search (optional)
│   ├── evaluation/
│   │   ├── compare.py               # Model vs baseline comparison
│   │   ├── promote.py               # Threshold check → promote model
│   │   └── by_category.py           # Per-category metrics
│   └── prompts/
│       ├── versions.json            # Prompt version history
│       └── templates/               # Fallback template store
│
├── data/
│   ├── synthetic/                   # Generated training data
│   │   ├── products.csv
│   │   ├── inventory.csv
│   │   ├── sales.csv
│   │   ├── traffic.csv
│   │   ├── competitor_prices.csv
│   │   └── labels.csv
│   ├── scripts/
│   │   ├── generate_synthetic.py    # Data generation script
│   │   └── seed_database.py         # Load CSVs into PostgreSQL
│   └── migrations/
│       └── (Alembic migration files)
│
├── dashboard/                        # React frontend
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── Dockerfile
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── api/                     # API client for EEP
│   │   ├── components/
│   │   │   ├── ActionList.tsx        # Weekly action list (main screen)
│   │   │   ├── RecommendationCard.tsx
│   │   │   ├── DetailModal.tsx       # SHAP chart, competitor table, margin sim
│   │   │   ├── MarginSimulator.tsx
│   │   │   ├── CompetitorTable.tsx
│   │   │   ├── CampaignPreview.tsx
│   │   │   ├── ApprovalButtons.tsx
│   │   │   └── ConfidenceBadge.tsx
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── AuditTrail.tsx
│   │   │   └── Upload.tsx
│   │   └── styles/
│   │       └── globals.css
│   └── public/
│
├── infra/
│   ├── k8s/
│   │   ├── namespace.yaml
│   │   ├── eep/
│   │   │   ├── deployment.yaml
│   │   │   ├── service.yaml
│   │   │   └── hpa.yaml
│   │   ├── ie1/
│   │   │   ├── deployment.yaml
│   │   │   └── service.yaml
│   │   ├── ie2/
│   │   │   ├── deployment.yaml
│   │   │   └── service.yaml
│   │   ├── ie3/
│   │   │   ├── deployment.yaml
│   │   │   └── service.yaml
│   │   ├── postgres/
│   │   │   ├── deployment.yaml
│   │   │   ├── service.yaml
│   │   │   └── pvc.yaml
│   │   ├── ingress.yaml
│   │   ├── secrets.yaml
│   │   └── configmap.yaml
│   └── monitoring/
│       ├── prometheus.yml
│       ├── alert_rules.yml
│       └── grafana/
│           └── dashboard.json
│
├── tests/
│   ├── unit/                        # Mirrors services/ structure
│   ├── integration/
│   │   ├── test_eep_to_ie1.py
│   │   ├── test_eep_to_ie2.py
│   │   ├── test_full_pipeline.py
│   │   └── golden/
│   │       └── test_golden_scenarios.py   # The 6 golden tests
│   └── e2e/
│       └── test_live_endpoint.py
│
├── docs/
│   ├── technical/
│   │   ├── architecture.md
│   │   ├── api_contracts.md
│   │   └── data_flow.md
│   ├── business/
│   │   ├── problem_statement.md
│   │   ├── persona.md
│   │   └── roi_analysis.md
│   └── mlops/
│       ├── training_pipeline.md
│       ├── promotion_criteria.md
│       └── retraining_strategy.md
│
└── .github/
    └── workflows/
        ├── ci.yml                   # Test + lint on every push
        └── deploy.yml               # Build + deploy on main merge
```

---

## 4. Team Roles & Responsibilities

Assign **ownership** so nobody steps on each other. Everyone touches everything, but one person **drives** each area.

| Member | Primary Ownership | Secondary |
|---|---|---|
| **Hassan** | **IE2 (Decision Intelligence)** — rules engine, CatBoost training, SHAP, ML pipeline, MLflow, synthetic data generation | Integration tests, golden scenarios |
| **Jawad** | **IE1 (Market Intelligence) + IE3 (Campaign Creative)** — competitor signals, seasonality, confidence scoring, Claude API integration, prompt engineering | Scraper background job, IE3 templates |
| **Farhat** | **EEP (Orchestrator) + Dashboard + Infra** — orchestration, circuit breakers, React dashboard, Docker, K8s, Prometheus, Grafana, CI/CD | Cloud deployment, documentation |

### Shared Responsibilities (all 3)

- Database schema creation and seeding
- Writing unit tests for your own service
- Code reviews (every PR needs 1 approval)
- Documentation for your service

---

## 5. Phase Breakdown (15 Days)

### Phase 1: Foundation (Days 1–3)

**Goal:** Repo scaffolded, database running, synthetic data generated and loaded, all 4 services return `/health` 200 OK.

### Phase 2: Core Services (Days 4–8)

**Goal:** IE1, IE2, IE3 fully working independently with unit tests. ML model trained and logged in MLflow.

### Phase 3: Integration & Dashboard (Days 9–11)

**Goal:** EEP orchestrates all 3 services end-to-end. Dashboard renders recommendations. Approve/reject flow works.

### Phase 4: Infrastructure & Polish (Days 12–13)

**Goal:** Docker Compose runs full stack. K8s manifests written. Prometheus + Grafana dashboards working. CI/CD pipeline green.

### Phase 5: Docs, Deploy & Demo (Days 14–15)

**Goal:** Cloud deployment live. All docs written. Demo rehearsed. Submission-ready.

---

## 6. Detailed Task Checklists

### PHASE 1 — Foundation (Days 1–3)

All 3 team members work together on this phase. Do it in a single session if possible.

#### Day 1 — Repo Setup & Database

```
ALL MEMBERS TOGETHER:
```

- [ ] Create GitHub repo `stylepulse-ai`, add all 3 members as collaborators
- [ ] Create the full folder structure from Section 3 (every directory, every `__init__.py`)
- [ ] Create `.gitignore` (Python + Node + Docker + .env)
- [ ] Create `.env.example` with all required environment variables:
  ```
  DATABASE_URL=postgresql+asyncpg://stylepulse:stylepulse@localhost:5432/stylepulse
  APIFY_TOKEN=
  ANTHROPIC_API_KEY=
  API_KEY=dev-key-123
  IE1_URL=http://localhost:8001
  IE2_URL=http://localhost:8002
  IE3_URL=http://localhost:8003
  MLFLOW_TRACKING_URI=http://localhost:5000
  ```
- [ ] Write `docker-compose.yml` with **only PostgreSQL + MLflow** for now (services added later)
- [ ] Run `docker compose up -d postgres mlflow` — verify both start
- [ ] Create `services/shared/models.py` — define all 8 SQLAlchemy ORM models:
  - `products`, `inventory`, `sales`, `traffic`, `competitor_prices`, `features`, `recommendations`, `campaigns`
- [ ] Create `services/shared/database.py` — async engine + session factory
- [ ] Create Alembic config, generate initial migration, apply it:
  ```bash
  cd services/shared
  alembic init migrations
  alembic revision --autogenerate -m "create_all_tables"
  alembic upgrade head
  ```
- [ ] Verify all 8 tables exist in PostgreSQL using `psql` or pgAdmin
- [ ] Create `Makefile` with shortcuts:
  ```makefile
  db-up:
      docker compose up -d postgres mlflow
  db-down:
      docker compose down
  seed:
      python data/scripts/seed_database.py
  test:
      pytest tests/ -v
  lint:
      ruff check .
  ```

#### Day 2 — Synthetic Data Generation

```
HASSAN leads, others review
```

- [ ] Write `data/scripts/generate_synthetic.py` that creates:
  - **products.csv** — 300 Adidas products with realistic names, style codes, categories, prices
    - Categories: `running_shoes`, `football_boots`, `training`, `lifestyle_sneakers`, `sportswear`, `outdoor`
    - Sport types: `running`, `football`, `training`, `lifestyle`, `outdoor`
    - Collection types: `core`, `seasonal`, `collab`, `limited`
    - Price range: cost $40-120, retail $80-280
    - Generate real-looking Adidas style codes (e.g., `HQ4202`, `GW9461`, `IF1234`)
  - **inventory.csv** — Daily snapshots for 12 months (365 days × 300 SKUs)
    - Simulate realistic stock patterns: restocking, selldowns, dead stock
    - Some products go to 0 (stockouts), some accumulate (dead stock)
  - **sales.csv** — Daily sales per SKU for 12 months
    - Seasonal patterns: running shoes peak Mar-May & Sep-Oct, football boots Aug-Dec
    - Weekend uplift, Black Friday spike, January sale spike
    - Some products sell 0 for weeks (dead stock signals)
  - **traffic.csv** — Daily page views, conversions for 12 months
    - Correlated with sales but with noise
    - Conversion rates 0.5%–5%
  - **competitor_prices.csv** — 8 competitors × 300 SKUs × 365 days
    - Prices within ±25% of retail, some on sale, some out of stock
    - Simulate sale events (Black Friday, January, etc.)
  - **labels.csv** — Assign ground-truth labels (HOLD/MARKDOWN/PROMOTE/CLEAR) per SKU per week
    - Use deterministic rules to create labels from the data itself
    - Distribution target: HOLD 45%, MARKDOWN 25%, PROMOTE 20%, CLEAR 10%
- [ ] Run the script, verify all CSVs look reasonable
- [ ] Write `data/scripts/seed_database.py` — loads all CSVs into PostgreSQL
- [ ] Run seed script, verify row counts match

#### Day 3 — Service Skeletons & Health Checks

```
FARHAT leads EEP, JAWAD leads IE1+IE3, HASSAN leads IE2
```

- [ ] Each service gets a minimal `main.py`:
  ```python
  from fastapi import FastAPI
  app = FastAPI(title="Service Name", version="0.1.0")

  @app.get("/health")
  async def health():
      return {"status": "healthy", "service": "service_name"}
  ```
- [ ] Each service gets a `requirements.txt`
- [ ] Each service gets a `Dockerfile` (multi-stage, non-root user)
- [ ] Update `docker-compose.yml` to include all 4 services + Postgres + MLflow
- [ ] Run `docker compose up --build` — all 4 services return 200 on `/health`
- [ ] Create a shared `conftest.py` for pytest with test database fixtures
- [ ] Each service: write 1 test that hits `/health` and asserts 200
- [ ] Run `pytest` — all health tests pass
- [ ] First meaningful commit: "Phase 1 complete: foundation, DB, synthetic data, all services healthy"

---

### PHASE 2 — Core Services (Days 4–8)

Team splits up. Each person works on their assigned services **in parallel**.

#### Days 4–5 — IE1: Market Intelligence (JAWAD)

- [ ] Define `schemas.py` — `CompetitorAnalysisRequest` and `CompetitorSignals` Pydantic models
- [ ] Implement `service.py`:
  - Read competitor prices for a `style_code` from `competitor_prices` table
  - Compute: `competitor_min_price`, `competitor_avg_price`, `price_gap_pct`
  - Count `competitors_on_sale_count`
  - Determine `price_trend_direction` (RISING / STABLE / FALLING)
  - Compute `data_freshness_hours` from `scraped_at`
- [ ] Implement `seasonality.py`:
  - Lookup table: category → month → score (1.0 / 0.6 / 0.1)
  - Function: `get_seasonality_score(category, sport_type, date) → float`
- [ ] Implement `calendar_events.py`:
  - Define all 8 calendar events with dates
  - Function: `get_next_event(date) → (event_name, days_until)`
- [ ] Implement `confidence.py`:
  - 3-tier scoring based on `data_freshness_hours`
  - Fresh (<6h) → 1.0, Stale (6-24h) → 0.7, Very stale (24-48h) → 0.4, No data → 0.2
  - Fallback: return neutral signals when confidence < 0.2
- [ ] Implement `routes.py` — `POST /analyze` endpoint
- [ ] Write unit tests (target: 15+ tests):
  - Happy path with fresh data
  - Stale data triggers fallback
  - Missing style code returns neutral signals
  - All competitors on sale
  - Seasonality scores for each category in peak/off months
  - Calendar proximity calculations

#### Days 4–5 — IE2: Decision Intelligence (HASSAN)

- [ ] Implement `rules_engine.py` — all 5 hard rules:
  - Rule 1: Dead Stock Clear (days_of_supply > 120 AND sell_through < 0.15)
  - Rule 2: Low Stock Protection (total_qty < 15 OR days_of_supply < 7)
  - Rule 3: Margin Floor Protection (price < cost × 1.15)
  - Rule 4: Recent Discount Protection (days_since_discount < 21)
  - Rule 5: Calendar Event Nudge (event ≤ 14 days AND stock > 30 days AND margin > 35%)
  - Each rule returns: `(triggered: bool, action: str, reason: str, override_strength: str)`
- [ ] Implement `ml_pipeline/features/engineer.py`:
  - Compute all 32 features from raw tables
  - Output `features.csv` with one row per SKU per week
  - Use pandas: joins, rolling windows, slopes
- [ ] Implement `ml_pipeline/features/validate.py`:
  - pandera schema: check types, ranges, null rates
  - Label distribution check (no class < 5%)
- [ ] Implement `ml_pipeline/training/train.py`:
  - Time-based split (9 months train / 2 months val / 2 months test)
  - CatBoost with `iterations=500, lr=0.05, depth=6, MultiClass`
  - Log to MLflow: params, metrics, confusion matrix, feature importance
- [ ] Implement `ml_pipeline/training/baseline.py`:
  - Simple rule baseline (days_of_supply based)
  - Log baseline metrics to MLflow for comparison
- [ ] Implement `ml_pipeline/evaluation/promote.py`:
  - Check: accuracy ≥ 0.80, macro_f1 ≥ 0.75, CLEAR_recall ≥ 0.88
  - Auto-promote to MLflow Model Registry if passing
- [ ] Implement `model_inference.py`:
  - Load model from MLflow
  - Predict + compute SHAP values
  - Return top 5 SHAP features per prediction
- [ ] Implement `explainer.py`:
  - Map feature names → plain English templates
  - `price_gap_pct = 0.12 (+0.34)` → "You are 12% more expensive than the cheapest competitor"
- [ ] Implement `reconciliation.py`:
  - If rule fired with ABSOLUTE strength → use rule, ignore model
  - If rule fired with STRONG strength → block specific classes
  - If rule fired with SOFT strength → add bias to model probabilities
  - If no rule fired → use model output directly
- [ ] Define `schemas.py` — `RecommendationResult`, `SHAPFeature`, `RuleOverride`
- [ ] Implement `routes.py` — `POST /recommend` endpoint
- [ ] Write unit tests (target: 20+ tests):
  - Each of the 5 rules with boundary conditions
  - Model returns valid 4-class probabilities
  - SHAP top 5 returned correctly
  - Confidence < 0.45 → HOLD fallback
  - All 4 decisions can be returned
  - Reconciliation logic for each override strength

#### Day 6 — IE3: Campaign Creative (JAWAD)

- [ ] Define `schemas.py` — `PromotionBrief` and `CampaignPackage`
- [ ] Implement `generator.py`:
  - Call Anthropic Claude API with system prompt + PromotionBrief
  - Parse response as JSON
  - Retry once on failure with stricter prompt
  - On second failure → use template fallback
- [ ] Implement `validator.py`:
  - Validate: headline ≤ 60 chars, instagram ≤ 300 chars, etc.
  - Check all required fields present
  - Set `generation_confidence` based on quality checks
- [ ] Create 4+ Jinja2 fallback templates in `templates/`:
  - `running_shoes.j2`, `football_boots.j2`, `lifestyle.j2`, `generic.j2`
- [ ] Create `prompt_versions.json` with v1.0 entry
- [ ] Implement `routes.py` — `POST /generate`
- [ ] Write unit tests (target: 10+ tests):
  - Happy path returns valid CampaignPackage
  - All character limits enforced
  - Schema failure triggers retry
  - Two failures trigger template fallback
  - `fallback_used=true` when template used
  - Prompt version logged

#### Days 6–8 — IE2 ML Training Execution (HASSAN)

- [ ] Run feature engineering pipeline end-to-end on synthetic data
- [ ] Validate features with pandera — fix any issues
- [ ] Train CatBoost model — first run, log to MLflow
- [ ] Train baseline model — log to MLflow
- [ ] Compare: model must beat baseline by ≥ 0.10 macro F1
- [ ] If not passing thresholds: tune hyperparameters, adjust class weights
- [ ] Generate artifacts: confusion matrix, feature importance chart, SHAP summary plot
- [ ] Promote best model to MLflow Model Registry
- [ ] Verify IE2 can load the promoted model and return predictions via `/recommend`

#### Days 7–8 — EEP Orchestrator (FARHAT)

- [ ] Define `schemas.py` — `RecommendationPackage` (the master response)
- [ ] Implement `orchestrator.py`:
  - Call IE1 → get `CompetitorSignals` (3s timeout)
  - Call IE2 with SKU features + CompetitorSignals → get `RecommendationResult` (5s timeout)
  - If decision == PROMOTE → call IE3 → get `CampaignPackage` (8s timeout)
  - Assemble `RecommendationPackage`
  - Always set `requires_human_approval = True`
- [ ] Implement `circuit_breaker.py`:
  - Per-service: track failures, open circuit after 3 failures in 60s
  - Fallback behaviors:
    - IE1 down → neutral signals (price_gap=0, confidence=0.2)
    - IE2 down → HOLD with reason "orchestrator_fallback"
    - IE3 down → return recommendation without campaign creative
- [ ] Implement `confidence_decay.py`:
  - Formula: `decay = max(0.3, 1.0 - (hours/72) * 0.5)`
  - `needs_refresh` if effective_confidence < 0.40 or hours > 72
- [ ] Implement `middleware.py`:
  - API key validation from `X-API-Key` header
  - Rate limiting: 10 req/min per key
- [ ] Implement routes:
  - `POST /recommend/{sku_id}` — single SKU
  - `POST /recommend/batch` — up to 50 SKUs
  - `POST /inventory/import` — save validated inventory rows to DB
  - `GET /recommendations` — list pending
  - `GET /status/{sku_id}` — with decay applied
  - `PATCH /review/{sku_id}` — approve/edit/reject/snooze
  - `GET /health`, `GET /metrics`
- [ ] Write unit tests (target: 15+ tests):
  - Full pipeline happy path
  - IE1 timeout → fallback
  - IE2 timeout → HOLD fallback
  - IE3 timeout → recommendation without creative
  - Batch endpoint with 50 SKUs
  - Rate limiting blocks excess requests
  - Confidence decay calculation

---

### PHASE 3 — Integration & Dashboard (Days 9–11)

#### Day 9 — Integration Testing

```
ALL MEMBERS TOGETHER
```

- [ ] Run all 4 services together via Docker Compose
- [ ] Test full pipeline end-to-end: EEP → IE1 → IE2 → IE3
- [ ] Implement the 6 Golden Scenarios in `tests/integration/golden/test_golden_scenarios.py`:
  1. Dead stock always gets CLEAR
  2. Low margin blocks MARKDOWN
  3. Low stock blocks PROMOTE
  4. Recent discount blocks MARKDOWN
  5. PROMOTE triggers IE3 campaign creative
  6. Stale competitor data degrades confidence
- [ ] All 6 golden scenarios must pass
- [ ] Write 5+ additional integration tests
- [ ] Fix any bugs discovered during integration

#### Days 10–11 — Dashboard (FARHAT, with help from team)

**If using React:**

- [ ] Initialize Vite + React + TypeScript project in `dashboard/`
  ```bash
  cd dashboard
  npm create vite@latest . -- --template react-ts
  npm install axios recharts tailwindcss @headlessui/react
  ```
- [ ] Create `api/client.ts` — axios instance pointing to EEP
- [ ] Build `ActionList.tsx` — main screen:
  - URGENT (red) — CLEAR items
  - MARKDOWN (orange) — markdown items
  - PROMOTE (green) — promote items
  - HOLD (grey, collapsed) — hold items
- [ ] Build `RecommendationCard.tsx` — one card per product
  - Product name, style code, decision badge, confidence bar
- [ ] Build `DetailModal.tsx` — opens on card click:
  - Plain English explanation (numbered SHAP reasons)
  - Competitor price comparison table
  - Margin simulator slider (if MARKDOWN)
  - Campaign creative preview (if PROMOTE)
  - Approve / Edit / Reject / Snooze buttons
- [ ] Build `MarginSimulator.tsx`:
  - Slider for discount %
  - Live-updating margin calculation
  - Margin floor warning
- [ ] Build `CampaignPreview.tsx`:
  - Show Instagram, Facebook, WhatsApp copy
  - Copy-to-clipboard buttons
- [ ] Build `Upload.tsx` — CSV upload page
- [ ] Build `AuditTrail.tsx` — history of all decisions
- [ ] Add Dockerfile for dashboard (nginx serving static build)

**If using Streamlit instead:**

- [ ] Create `dashboard/app.py` with Streamlit
- [ ] Same pages: Action List, Detail View, Upload, Audit Trail
- [ ] Deploy as Docker container

---

### PHASE 4 — Infrastructure & Polish (Days 12–13)

#### Day 12 — Docker, K8s, Monitoring (FARHAT leads)

- [ ] Finalize all 4 Dockerfiles (multi-stage, non-root, health checks)
- [ ] Finalize `docker-compose.yml` with ALL services:
  - EEP, IE1, IE2, IE3, Postgres, MLflow, Prometheus, Grafana, Dashboard
- [ ] Test: `docker compose up --build` — everything starts and communicates
- [ ] Add Prometheus instrumentation to all services:
  - `prometheus-fastapi-instrumentator` package
  - Custom metrics per service (see spec Section 13)
- [ ] Create `infra/monitoring/prometheus.yml` — scrape all 4 services
- [ ] Create `infra/monitoring/grafana/dashboard.json` — 10 panels:
  1. Requests/sec per service
  2. P50/P95 latency
  3. Error rate per service
  4. Fallback rates
  5. Decision distribution pie chart
  6. Model confidence over time
  7. Approval rate
  8. IE3 trigger rate
  9. Competitor data freshness
  10. Monthly revenue impact estimate
- [ ] Write Kubernetes manifests in `infra/k8s/`:
  - Namespace, Deployments, Services, HPA, Ingress, Secrets, ConfigMap
  - IE1/IE2/IE3 are ClusterIP (internal only)
  - EEP is LoadBalancer (public)
- [ ] Test with Minikube:
  ```bash
  minikube start
  kubectl apply -f infra/k8s/namespace.yaml
  kubectl apply -f infra/k8s/ --recursive
  kubectl get pods -n stylepulse
  ```
- [ ] Screenshot Minikube cluster running for submission

#### Day 13 — CI/CD + Testing Cleanup (ALL)

- [ ] Create `.github/workflows/ci.yml`:
  - Trigger: push to any branch
  - Steps: checkout, setup Python, install deps, lint (ruff), run pytest
- [ ] Create `.github/workflows/deploy.yml`:
  - Trigger: push to main
  - Steps: build Docker images, push to registry, deploy to Railway/Render
- [ ] Run full test suite — aim for 80+ unit tests, 20+ integration, 6 golden:
  ```bash
  pytest tests/ -v --tb=short
  ```
- [ ] Fix any failing tests
- [ ] Code cleanup: remove dead code, add docstrings, type hints

---

### PHASE 5 — Docs, Deploy & Demo (Days 14–15)

#### Day 14 — Documentation & Cloud Deploy

```
ALL MEMBERS — split docs by ownership
```

- [ ] **FARHAT:** Deploy to Railway.app or Render.com:
  - Deploy all 4 services + Postgres
  - Verify live `/health` endpoints
  - Verify full pipeline works on cloud
  - Get the public URL
- [ ] **HASSAN:** Write ML/technical docs:
  - `docs/mlops/training_pipeline.md` — how to train, what gets logged
  - `docs/mlops/promotion_criteria.md` — threshold table
  - `docs/mlops/retraining_strategy.md` — when and how to retrain
  - `docs/technical/architecture.md` — system diagram, service interactions
  - `docs/technical/api_contracts.md` — all endpoints, request/response schemas
  - `docs/technical/data_flow.md` — step-by-step data flow
- [ ] **JAWAD:** Write business docs:
  - `docs/business/problem_statement.md` — the pain point, market size
  - `docs/business/persona.md` — SportEdge owner profile
  - `docs/business/roi_analysis.md` — cost savings, ROI projections
- [ ] Write `CHANGELOG.md` with daily progress entries
- [ ] Polish `README.md` — the one in the repo root (separate from this plan)

#### Day 15 — Demo Prep & Final Submission

- [ ] Rehearse the 10-minute demo script (see spec Section 16):
  1. Show live `/docs` endpoint
  2. Submit dead-stock SKU → show CLEAR with rule override
  3. Submit healthy SKU → show PROMOTE with campaign creative
  4. Show stale data fallback
  5. Open dashboard → weekly action list
  6. Approve a recommendation → audit trail
  7. Open Grafana → show metrics panels
  8. Open MLflow → show experiment tracking
- [ ] Record a backup demo video (Loom or OBS)
- [ ] Final commit: "v1.0 — submission ready"
- [ ] Tag release: `git tag v1.0 && git push --tags`
- [ ] Verify:
  - [ ] GitHub repo has meaningful commit history (not 1 giant commit)
  - [ ] All tests pass on CI
  - [ ] Cloud deployment is live
  - [ ] README has live URL, setup instructions, demo video link
  - [ ] All docs present in `docs/` folder

---

## 7. Synthetic Data Strategy

Since you don't have a real Adidas retailer's data, you **must** generate realistic synthetic data. This is the foundation of everything.

### Data Generation Rules

```python
# Product name patterns
PRODUCT_TEMPLATES = [
    "Adidas Ultraboost {version}",
    "Adidas NMD_R1 {colorway}",
    "Adidas Stan Smith {variant}",
    "Adidas Predator {version}",
    "Adidas Terrex {model}",
    "Adidas Tiro {year} {item}",
    "Adidas Forum {variant}",
    "Adidas Gazelle {colorway}",
    # ... 20+ templates
]

# Style code generation: 2 letters + 4 digits
import random, string
def gen_style_code():
    return random.choice(string.ascii_uppercase) + random.choice(string.ascii_uppercase) + \
           str(random.randint(1000, 9999))

# Seasonal sales multipliers
SEASONAL_MULTIPLIERS = {
    "running_shoes": {3: 1.5, 4: 1.8, 5: 1.6, 9: 1.7, 10: 1.5},  # Spring + Fall
    "football_boots": {8: 1.8, 9: 2.0, 10: 1.5, 11: 1.3},          # Season start
    "lifestyle_sneakers": {4: 1.3, 5: 1.5, 6: 1.4, 7: 1.3},        # Summer
    # ...
}

# Black Friday spike: month=11, day 25-30 → sales × 3.0
# January sale: month=1, day 1-15 → sales × 2.0
```

### Label Assignment Logic

Generate labels deterministically from the data, not randomly:

```
IF days_of_supply > 120 AND sell_through < 0.15 → CLEAR
IF days_of_supply > 60 AND velocity_ratio < 0.5 AND price_gap > 0.10 → MARKDOWN
IF seasonality_score > 0.7 AND stock > 30 days AND margin > 0.30 → PROMOTE
ELSE → HOLD
```

Target distribution: **HOLD 45% | MARKDOWN 25% | PROMOTE 20% | CLEAR 10%**

---

## 8. ML Pipeline Checklist

Run these commands in order after synthetic data is seeded:

```bash
# Step 1: Generate features
python -m ml_pipeline.features.engineer

# Step 2: Validate features
python -m ml_pipeline.features.validate

# Step 3: Train baseline
python -m ml_pipeline.training.baseline

# Step 4: Train CatBoost
python -m ml_pipeline.training.train

# Step 5: Compare model vs baseline
python -m ml_pipeline.evaluation.compare

# Step 6: Promote if passing
python -m ml_pipeline.evaluation.promote

# Step 7: Verify model loads in IE2
curl -X POST http://localhost:8002/recommend \
  -H "Content-Type: application/json" \
  -d '{"sku_id": "SKU-001", "features": {...}}'
```

---

## 9. API Contracts Quick Reference

### IE1 — POST /analyze
```
Request:  { sku_id, style_code, product_name, category, sport_type, retail_price, cost_price, season, launch_date }
Response: { sku_id, competitor_min_price, competitor_avg_price, price_gap_pct, competitors_on_sale_count,
            cheapest_competitor_name, price_trend_direction, seasonality_alignment_score,
            calendar_event_proximity_days, next_calendar_event, data_freshness_hours,
            confidence_score, fallback_used, fallback_reason, timestamp }
```

### IE2 — POST /recommend
```
Request:  { sku_id, features: {32 features}, competitor_signals: {IE1 output} }
Response: { sku_id, recommendation, confidence, explanation, shap_top5, rule_override,
            suggested_price, margin_after_action, fallback_used }
```

### IE3 — POST /generate
```
Request:  { sku_id, product_name, category, sport_type, retail_price, discount_pct,
            key_features, target_audience, urgency_level, stock_remaining, season,
            calendar_event, brand }
Response: { sku_id, headline, subheadline, ad_copy_short, ad_copy_long, instagram_post,
            facebook_post, whatsapp_broadcast, cta_primary, cta_secondary, tone_used,
            prompt_version, generation_confidence, fallback_used }
```

### EEP — POST /recommend/{sku_id}
```
Response: { sku_id, product_name, recommendation, confidence, effective_confidence,
            explanation, shap_explanation, rule_override, competitor_signals,
            suggested_price, margin_after_action, campaign_creative,
            requires_human_approval: true, freshness_score, needs_refresh,
            processing_time_ms, generated_at, service_versions }
```

---

## 10. Infrastructure & Deployment Plan

### Local Development Stack

```bash
# Start everything locally
docker compose up --build

# Services available at:
# EEP:        http://localhost:8000/docs
# IE1:        http://localhost:8001/docs
# IE2:        http://localhost:8002/docs
# IE3:        http://localhost:8003/docs
# PostgreSQL: localhost:5432
# MLflow:     http://localhost:5000
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3000
# Dashboard:  http://localhost:5173 (Vite dev) or http://localhost:80 (Docker)
```

### Cloud Deployment (Railway.app — recommended)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and init
railway login
railway init

# Deploy each service
railway up -s eep
railway up -s market-intelligence
railway up -s decision-intelligence
railway up -s campaign-creative
railway up -s postgres
```

**Cost: $0-5/month on Railway free tier for demo purposes.**

### Kubernetes (Minikube — for course requirement)

```bash
# Start Minikube
minikube start --memory=4096 --cpus=2

# Apply all manifests
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/ --recursive

# Verify
kubectl get pods -n stylepulse
kubectl get services -n stylepulse

# Access EEP
minikube service eep -n stylepulse --url
```

---

## 11. Testing Plan

### Test Count Targets

| Layer | Target | Owner |
|---|---|---|
| IE1 unit tests | 15+ | Jawad |
| IE2 unit tests | 20+ | Hassan |
| IE3 unit tests | 10+ | Jawad |
| EEP unit tests | 15+ | Farhat |
| Integration tests | 10+ | All |
| Golden scenarios | 6 (mandatory) | All |
| E2E tests | 5+ | Farhat |
| **Total** | **80+** | |

### Running Tests

```bash
# All tests
pytest tests/ -v

# Unit tests only
pytest tests/unit/ -v

# Integration tests only
pytest tests/integration/ -v

# Golden scenarios only
pytest tests/integration/golden/ -v

# Single service tests
pytest services/market_intelligence/tests/ -v

# With coverage
pytest tests/ --cov=services --cov-report=html
```

---

## 12. Risk Register & Mitigations

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| ML model doesn't meet thresholds | Medium | High | Tune class weights, add more features, adjust thresholds slightly. Synthetic data gives you control. |
| Claude API rate limit / cost | Low | Medium | Use haiku (cheapest), cache responses, fallback templates are ready |
| Docker Compose won't start | Medium | High | Test incrementally — start with 1 service, add one at a time |
| Team member falls behind | Medium | High | Daily standups, help each other, swap tasks if needed |
| React takes too long to learn | Medium | Medium | Switch to Streamlit (Python only, 1 day to build) |
| Cloud deployment fails | Low | Medium | Demo locally with Docker Compose. Pre-record backup video. |
| Database migration issues | Low | Medium | Use Alembic, test migrations on empty DB first |
| Scraper code from prototype doesn't fit | Low | Low | Ignore the prototype. Build IE1 scraper fresh using Apify API. |

---

## 13. Daily Standup Protocol

Every day, 15 minutes max. Each person answers:

1. **What did I finish yesterday?**
2. **What am I working on today?**
3. **Am I blocked on anything?**

Use a shared WhatsApp/Discord group for async updates. Push code daily — never go 2 days without a commit.

### Git Workflow

```
main          ← production-ready, protected
├── dev       ← integration branch, merge PRs here
├── feat/ie1  ← Jawad's IE1 + IE3 work
├── feat/ie2  ← Hassan's IE2 + ML work
└── feat/eep  ← Farhat's EEP + dashboard + infra
```

- Feature branches merge into `dev` via PR (1 review required)
- `dev` merges into `main` when phase is complete
- Tag releases: `v0.1` (Phase 1), `v0.2` (Phase 2), etc.

---

## 14. Definition of Done

A task is DONE when:

- [ ] Code is written and committed
- [ ] Unit tests pass
- [ ] No lint errors (`ruff check .`)
- [ ] Docker container builds and starts
- [ ] `/health` endpoint returns 200
- [ ] PR reviewed by at least 1 teammate
- [ ] Relevant documentation updated

The **project** is DONE when:

- [ ] All 6 golden scenarios pass
- [ ] 80+ unit tests pass
- [ ] Full pipeline: EEP → IE1 → IE2 → IE3 works end-to-end
- [ ] Dashboard renders and approve/reject works
- [ ] Docker Compose starts the full stack
- [ ] K8s manifests apply without errors
- [ ] Grafana dashboard shows real metrics
- [ ] MLflow has training runs with artifacts
- [ ] Cloud deployment is live with public URL
- [ ] All docs written
- [ ] Demo rehearsed and backup video recorded

---

> **Remember:** This plan is aggressive but achievable with 3 people working focused hours every day. The key is parallel work during Phase 2 — each person builds their service independently, then you integrate in Phase 3. Don't waste time on perfection in Phase 1-2. Get things working first, then polish in Phase 4-5.
>
> **The scraping prototype in this repo was a proof of concept.** It proved style-code matching works. Now build the real thing from scratch with a clean architecture.

---

*Generated for Team: Hassan Fouani · Mohammad Jawad · Mohammad Farhat*
*Project: StylePulse AI — AI-Powered Pricing & Promotion Intelligence*
*Timeline: 15 days starting April 7, 2026*
