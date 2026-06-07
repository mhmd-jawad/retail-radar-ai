# Retail Radar AI — Project Status & Gap Analysis

**Course:** EECE503N / EECE798N — AI Engineering, Final Project (40%)
**Date:** 2026-06-07
**Scope of this document:** everything the rubric requires **except** Deployment, Kubernetes, and CI/CD — those three are tracked separately (k3s deployment guide already delivered; CI/CD plan already delivered). This file covers *all the other* gaps and improvements.

> **Legend:** ✅ Done · �️ Partial (exists but not rubric-complete) · ❌ Missing · 💪 Already a strength

---

## 1. Scorecard at a glance

| # | Rubric requirement | Status | One-line verdict |
|---|---|---|---|
| §3.1 | Novelty claim + business problem + "who pays" | 🟡 | Business case is in README; **explicit novelty claim + non-AI baseline comparison missing**. |
| §3.1 | Explicit **non-AI baseline** + justification | 🟡 | A rules engine baseline exists in code; **not documented or benchmarked vs the model**. |
| §4 | EEP + ≥2 independent IEPs | ✅/🟡 | EEP + IE1/IE2/IE3 exist. But EEP runs IE2 **in-process** and **IE1 is a 72-line stub** — needs justification. |
| §5 | **Tradeoffs** section (3 + evidence) | ❌ | **Not written.** Only one passing "tradeoff" mention in PLAN.md. Required — penalized if absent. |
| §6 | Git discipline (branches, PRs, reviews) | 🟡 | Work happens on `dev`; **no PR/review trail or prompt-version history**. |
| §7 | MLOps pipeline (train→eval→promote) | 🟡💪 | MLflow + train/eval/`promote.py` + 54 tracked trials. **Strong, but promotion is manual scripts, not an automated pipeline.** |
| §7 | LLMOps — prompt versioning + eval | 🟡 | IE3 has a `prompt_version="v1.0"` constant; **no version history or eval evidence for prompt changes**. |
| §8.1 | Unit + integration + **E2E on deployed system** | 🟡 | Unit/integration/golden exist (20 files). **No E2E test that calls the deployed URL.** Must verify suite is green. |
| §8.2 | Regression / golden / data validation | ✅💪 | Golden scenarios + edge-case benchmark + schema validation. Good. |
| §9 | ≥3 Docker images + Compose | ✅ | 6 Dockerfiles + compose. (k8s tracked separately.) |
| §10 | Cloud deploy + arch + secrets + **cost** | 🟡 | Deployed (Lightsail + RDS). **Secrets = flat `.env`; no cost estimate; arch doc thin.** |
| §11 | Prometheus + Grafana, **per-service** metrics | 🟡 | EEP + IE2 instrumented well. **IE1 and IE3 expose no `/metrics`.** Need p50/p95, error-rate-by-type, throughput per service. |
| §11 | ≥1 ML-specific signal | ✅ | `ie2_avg_confidence` gauge + live RDS eval metrics. Can add a drift proxy. |
| §12 | Input validation + **rate limits** + failure modes | 🟡 | Validation ✅. **Rate limiting absent.** Inter-service timeouts ✅ but no retries/circuit-breakers; IE1/IE3 unauthenticated. |
| §14 | Technical + business docs | 🟡 | Several `docs/` exist; **business doc, architecture diagram, tradeoffs, cost are missing/thin.** |

---

## 2. The gaps in detail (what to actually do)

### A. Documentation gaps

#### A1. Tradeoffs section — ❌ **(required, highest-value-per-hour)**
The rubric explicitly requires a **Tradeoffs** section: ≥3 engineering tradeoffs, what you chose and rejected, **with evidence**. You have the raw material from real decisions in this codebase — just write it up with numbers:

1. **In-process IE2 vs. separate IE2 service.** EEP imports `decision_intelligence.main._recommend_single` *and* a standalone IE2 runs on `:8002`. Chosen in-process for the small Lightsail box (one model copy, lower latency, no network hop) at the cost of weaker service isolation. Evidence: measure `/recommend` latency in-process vs. over HTTP; note the ~1.5–2 GB RAM per model copy.
2. **CatBoost + hard rules vs. pure ML.** You gate the model with hard business rules and a 0.45 confidence fallback to HOLD. Chosen for safety/explainability over raw model autonomy. Evidence: the model's **CLEAR recall ≈1.7%** on the stress set (`meta.json`) — the rule layer is what actually catches dead stock. This is a genuine reliability-vs-complexity tradeoff with hard numbers.
3. **Synthetic/AI labels vs. waiting for real outcomes.** Model trained on `ai_label` (heuristic labels) so the system could ship before real sales accumulate. Evidence: val accuracy 99.8% (label-circularity) vs. real-test 96.5% — quantify the gap and explain the closed-loop `outcome_tracking` plan to replace it.
4. (Optional 4th) **Daily batch scrape via Apify vs. real-time.** Cost/freshness tradeoff: ~362k snapshots/day at low cost vs. stale-by-up-to-24h prices, mitigated by the `data_freshness_hours` confidence decay.

→ Write `docs/TRADEOFFS.md` and link it from the README.

#### A2. Non-AI baseline — 🟡 **(required)**
You already have the baseline: `services/decision_intelligence/training/baseline.py`, the `_rules_only_decision` path, and the StylePulse rule engine that drives the dashboard list. **Benchmark them head-to-head** and publish the table: rules-only vs. CatBoost accuracy/macro-F1 on the real test set, and *why* the ML lift justifies the added complexity. The `evaluation/edge_case_benchmark.py` and `model_only_edge_case_benchmark.py` already give you the harness.

#### A3. Novelty / positioning — 🟡
README has the problem and the buyer (small Adidas/multi-brand Lebanese retailers). Add an explicit, defensible **novelty claim** ("competitor-price + seasonality + inventory → single weekly HOLD/MARKDOWN/PROMOTE/CLEAR decision with human approval, for a market with no existing tool") and one sentence on why generic BI/Excel is insufficient.

#### A4. Secrets management + cost estimate — 🟡 **(required by §10)**
- **Secrets:** today it's a flat `.env` with real RDS/Apify/webhook secrets (and placeholder `AUTH_TOKEN_SECRET`/admin password). Document the *approach* and improve it: k8s `Secret`/Docker secrets, rotation policy, and least-privilege. (See the security backlog below — several secrets need rotating.)
- **Cost:** write a small table — RDS instance class, Lightsail/VM, Apify plan, LLM (OpenRouter/Gemini/Anthropic) per-1k-calls, egress. Identify the cost driver (likely Apify scraping + LLM creative).

→ Write `docs/DEPLOYMENT_ARCHITECTURE.md` (arch diagram + secrets + cost).

---

### B. Quality Assurance gaps

#### B1. End-to-end test on the deployed system — ❌ **(required, demo-critical)**
There is no `tests/e2e`. Add a test that hits the **public URL** (not localhost): login → fetch report → request a recommendation → assert shape/decision. This is the "if the system fails during the demo, grading stops" insurance. Wire it as a post-deploy smoke test too.

#### B2. Verify the suite is green + integration-across-services — 🟡
The README badge says "tests pending." Before the demo: run `pytest -q`, fix reds, and make sure at least one integration test exercises **EEP → IE2 → (IE3)** together. Then make CI run it (CI plan already drafted).

#### B3. LLM non-determinism testing (IE3) — 🟡
The rubric requires you to state **how you test LLM components despite non-determinism**. Define it: structural assertions (JSON schema/length/required fields), banned-content checks, and a small golden set scored with tolerance — not exact-string equality. Document in `docs/TESTING.md`.

---

### C. Observability gaps

#### C1. IE1 and IE3 have no metrics — 🟡 **(required: ≥1 metric per service)**
Only EEP (`eep/observability.py`) and IE2 (`services/decision_intelligence/main.py`) expose Prometheus. Add a `prometheus-fastapi-instrumentator` (or `make_asgi_app`) to **IE1 (`market_intelligence`)** and **IE3 (`campaign_creative`)** so every service has `/metrics`.

#### C2. Required signals per service — 🟡
Ensure each service emits, and Grafana panels show:
- **Latency p50 + p95** (histogram → `histogram_quantile`).
- **Error rate by type/class** (counter labelled by error class / HTTP status).
- **Throughput** (request volume).
You have the IE2 ML signal (`ie2_avg_confidence`, decision/fallback counters) — keep it and consider adding an **input-drift proxy** (e.g., rolling mean of `price_gap_pct` / `days_of_supply`, or `data_freshness_hours` distribution) to satisfy "output/input distribution shift."

#### C3. Dashboards — 🟡
Two Grafana dashboards exist (`stylepulse-eep`, `live-rds-evaluation`). Add/extend panels so **all four services** appear with the three core signals above, and add an alert rule example (even if alerting is "ready" not wired).

---

### D. Security & robustness gaps

#### D1. Rate limiting / abuse resistance — ❌ **(required)**
No limiter anywhere. Add `slowapi` (or a Caddy/ingress rate limit) on EEP's public endpoints — at least on `/auth/*`, `/recommend/*`, and the Apify webhook. This is an explicit §12 requirement.

#### D2. Inter-service failure modes — 🟡
EEP calls IE1/IE3 with timeouts (good) but **no retries, no circuit breaker, no explicit fallback** when an IE is down. Add bounded retries + a fallback (e.g., EEP returns the rules-only decision if IE2 errors) and document it. DB layer already has retries.

#### D3. Internal service auth — 🟡
IE1 and IE3 are unauthenticated (kept "internal"). In k8s keep them `ClusterIP`-only; if ever exposed, add the same `X-API-Key` IE2 uses. Document the trust boundary.

#### D4. Secret hygiene — 🟡 (carryover, important)
Rotate the exposed RDS password / `APIFY_TOKEN` / `APIFY_WEBHOOK_SECRET`; set a real `AUTH_TOKEN_SECRET` and admin password (both are still placeholders); remove/disable the default `admin@example.com`.

---

### E. MLOps / LLMOps gaps

#### E1. Automate the train→eval→promote pipeline — 🟡💪 **(you're close)**
You have the pieces: `training/train.py`, `training/register_model.py`, `evaluation/promote.py`, `evaluation/edge_case_benchmark.py`, MLflow tracking, and `meta.json` with per-trial thresholds. **Gap:** it runs as manual scripts. Turn it into **one automated pipeline** (a `make`/script or a CI job, e.g. `.github/prompts/test-promote-pipeline.prompt.md` already hints at this) that: trains → evaluates against thresholds + golden/edge cases → **promotes only if it beats the champion** → otherwise no-op/rollback. Document the **promotion thresholds and decision logic** explicitly (e.g., "promote if real-test macro-F1 ≥ champion and no golden regression").

#### E2. Model versioning clarity — 🟡
Health reports `retail_radar_decision_model_v6` but `meta.json.best_trial` points at a different export dir. Pin a single source of truth (the registered MLflow model + version) and have the service log exactly which artifact is live.

#### E3. LLM prompt versioning — 🟡 **(required if LLMs used — §6)**
IE3's `_TEXT_SYSTEM_PROMPT` / `_IMAGE_SYSTEM_PROMPT` are inline constants with a static `prompt_version="v1.0"`. Track prompt versions properly: keep them in a versioned file, bump the version on change, and record **eval evidence** (before/after on the IE3 golden set) justifying each change. This is explicitly graded.

---

### F. Architecture / engineering debt (from the earlier full audit)

These aren't new rubric items but they affect "robustness," "engineering maturity," and the live-demo:

- **DB schema drift / no migrations.** Live RDS diverges from `infra/postgres/*.sql` (dead `core.users`, undocumented `whatsapp` schema, runtime auto-DDL). Adopt a migration tool (Alembic) and capture the drift so the DB is reproducible.
- **No connection pooling.** EEP opens a fresh psycopg connection per request; RDS `max_connections=79`. Add PgBouncer before scaling (already in the k3s plan).
- **Two model copies in memory** (standalone IE2 + EEP in-process). Fine if justified in Tradeoffs; otherwise consolidate.
- **List-vs-drawer decision mismatch.** Dashboard list decisions come from the StylePulse **rule engine**; the drawer uses **CatBoost**. They can disagree for the same SKU — reconcile or label clearly.
- **Image bloat.** 138 MB of unused `trial_*.cbm` ship in the IE2/EEP image — add to `.dockerignore`.
- **README accuracy.** README claims structure/CI/cloud that don't match reality (e.g., "GitHub Actions," `dashboard/`). Update it.

---

## 3. Prioritized backlog (do in this order)

### P0 — Demo-blockers / required-and-missing (do first)
1. **Write `docs/TRADEOFFS.md`** (§5) — 3–4 tradeoffs with the evidence above.
2. **Add an E2E test** hitting the deployed URL (§8.1) and verify the whole suite is green.
3. **Add rate limiting** on EEP public routes (§12).
4. **Add `/metrics` to IE1 and IE3** + Grafana panels with p50/p95, error-rate, throughput for all 4 services (§11).
5. **Rotate secrets + set real `AUTH_TOKEN_SECRET`/admin password** (§10/§12).

### P1 — Required-but-partial (raises the grade)
6. **Non-AI baseline benchmark** table (§3.1) using the existing rules engine.
7. **Automate train→eval→promote** with documented thresholds + rollback (§7).
8. **Prompt versioning + eval evidence** for IE3 (§6/§7).
9. **`docs/DEPLOYMENT_ARCHITECTURE.md`** with diagram, secrets approach, **cost estimate** (§10).
10. **Inter-service retries + fallback** (EEP→IE) and document failure modes (§12).
11. **LLM testing strategy** doc (§8.2).

### P2 — Maturity / polish (competitive edge)
12. Alembic migrations + capture schema drift; PgBouncer.
13. Reconcile list-vs-drawer decisions; pin model version source of truth.
14. Input-drift proxy metric; example alert rule.
15. Git discipline: feature branches + PRs with review notes; fix README accuracy; `.dockerignore` the model trials.

---

## 4. What's already strong (don't undersell these)

- 💪 **Real, layered architecture** — EEP orchestrator + 3 distinct internal services (market signals / ML decision / LLM creative), genuinely different logic.
- 💪 **Real MLOps depth** — MLflow experiment tracking, 54 logged trials with full metrics, exported/registered models, an evaluation + promotion script, golden + edge-case benchmarks, and a closed-loop `outcome_tracking` schema.
- 💪 **Explainability** — SHAP top-5 turned into plain-English reasons surfaced in the UI.
- 💪 **A live data pipeline** — Apify → webhook → RDS, ~362k competitor snapshots, actually running daily.
- 💪 **Human-in-the-loop** by design — every recommendation requires approval.
- 💪 **Multi-tenant** auth with admin/shop separation (recently hardened: approvals, impersonation read-only, combined inbox).

The foundation is well above "CRUD-with-a-model." The remaining work is mostly **making the engineering rigor visible** (tradeoffs, baseline numbers, per-service metrics, E2E, rate limits) rather than building new features.
