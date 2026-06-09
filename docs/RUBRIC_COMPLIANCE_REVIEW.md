# Rubric Compliance Review — StylePulse AI / Retail Radar AI

**Course:** EECE503N / EECE798N — AI Engineering, Final Project (40%)
**Reviewed against:** (1) `EECE503N_798SN_SP26.pdf` (project spec) and (2) the Rubric Assessment
Template (graded categories T/S/P/D/C/Q/G/M/B + gates GT1–GT5).
**Date of review:** 2026-06-08
**How to read this:** for every requirement in the spec, you get **what you did** (with file
references) and **what's missing or weak** (if anything). Items are grouped by the spec's own
section numbers, then mapped to the rubric's scored categories at the end.

---

## 0. Baseline Gates (GT1–GT5) — pass/fail, not weighted

| Gate | Requirement | Status | Notes |
|---|---|---|---|
| **GT1** | Demo works end-to-end | ⚠️ Likely yes, **unverified** | You have a deployed system at `retailradar.site` and a working dashboard (verified visually this session). But there's **no automated E2E test against the live URL** — see §8.1. The rubric's hard rule is "if the system fails during the demo, grading stops," so this gate must be re-checked live, right before presenting. |
| **GT2** | Public cloud API functional | ✅ Yes | Deployed on Lightsail + RDS (per `docs/PROJECT_GAP_ANALYSIS.md` and `infra/`), reachable at a public domain. |
| **GT3** | Architecture minimum met (EEP + 2 IEPs) | ✅ Yes | EEP (`eep/`) + 3 IEPs (`market_intelligence`, `decision_intelligence`, `campaign_creative`) — exceeds the minimum of 2. |
| **GT4** | Required deliverables complete | ⚠️ Partial | Repo ✅, deployment ✅, demo (assume ✅ live), but **Tradeoffs doc was missing until this session** (now written, see §5) and a **business/architecture doc is thin**. |
| **GT5** | Type-specific minimum met (application-oriented) | ✅ Yes | You're clearly application-oriented (see §3.1) — non-AI baseline exists in code, business problem is stated, "who pays" is named. |

**Bottom line on gates:** you should clear all five, but GT1 and GT4 have soft spots (no scripted live E2E proof, and documentation gaps that were only partially closed as of this session). Treat these as your two highest-priority items before submission.

---

## 1. Core Learning Goals (from the Overview)

> "Your project must make the following visible and **defensible**: Quality Assurance, Tradeoff visibility, Real cloud deployment, Full observability."

| Goal | What you did | What's missing |
|---|---|---|
| **Quality Assurance** | `tests/unit/` (14 files) + `tests/integration/` (golden scenarios, IE2 model test, promote-pipeline test) — see `tests/`. Edge-case benchmark + schema validation in `data/evaluation`. | No **end-to-end test against the deployed system** (§8.1 below — this is the single highest-leverage gap). |
| **Tradeoff visibility** | A `Tradeoffs` section did **not exist** before this session. | ✅ **Now written**: `docs/TRADEOFFS.md`, with 4 tradeoffs, each stating what you chose, what you rejected, why, and quantified evidence pulled from `services/decision_intelligence/models/catboost_decision/meta.json` (e.g., `CLEAR` recall collapsing from 1.00 on validation to **0.017** on the adversarial stress set; validation accuracy 0.998 vs. real-test accuracy 0.965). Link it from the README. |
| **Real cloud deployment** | Deployed on AWS Lightsail + RDS, k3s manifests in `infra/k8s/`, public domain `retailradar.site`. Not a local demo. | Document the **deployment architecture diagram + secrets approach + cost estimate** explicitly (§10) — currently scattered across `docs/*.md`, not consolidated into one deliverable doc. |
| **Full observability** | Prometheus + Grafana running (`infra/monitoring/`), EEP and IE2 expose `/metrics` with `ie2_avg_confidence` ML signal. | **IE1 (`market_intelligence`) and IE3 (`campaign_creative`) expose no `/metrics`** — "at least one meaningful metric per service" (§11) is not yet met for all 4 services. |

---

## 2. Section 1 — Team Structure and Expectations

> "Teams of up to three students... Working solo or in pairs is allowed, with no reduction in expectations."

This is informational, not a scored deliverable — no action item. Per the rubric assessment
template you're listed as **Team 4 — "StylePulse AI" — Fouani, Hassan / Farhat, Mohamad
Jaafar / Jawad, Mohammad**. Make sure all three names and roles are visible in the README
"Team" section (`README.md` line ~359) and in commit history (see §6 — git ownership is
graded).

---

## 3. Section 2 — Project Scope and Philosophy

> "This project is **not**: a CRUD app with a model, a thin wrapper around an external API, a notebook-as-service, a demo-grade prototype."

**What you did:** You clearly clear this bar. The system has a real multi-service
architecture, a trained/tracked ML model (not just an API call), human-in-the-loop approval
workflows, multi-tenancy, a live data-collection pipeline (Apify → RDS), and a closed-loop
outcome-tracking design. This is a "production-oriented AI system" by any reasonable reading.

**What's missing:** Nothing structural. The risk here isn't that you *are* a thin wrapper —
it's that a grader skimming the README might initially mistake the LLM-creative IEP (IE3,
which calls the Anthropic/Claude API) for "just an API wrapper." Make sure your demo and docs
foreground the **CatBoost decision engine + rules + SHAP explainability + closed-loop
tracking** (the genuinely non-trivial AI work) rather than leading with the LLM copy-writing
feature.

---

## 4. Section 3 — Idea and Positioning

### 4.1 — Application-Oriented Projects (§3.1, your track)

The spec requires you to clearly define five things and include two more. Going through each:

| Required item | What you did | What's missing |
|---|---|---|
| **Novelty claim** ("not done before, or explicit novelty claim") | README states the problem/solution but does **not** make an explicit, defensible novelty claim. | Add one sentence: e.g., *"No existing tool combines competitor-price tracking + Adidas seasonal calendar + inventory age into a single weekly HOLD/MARKDOWN/PROMOTE/CLEAR decision with human approval, for small single-brand retailers in the Lebanese market."* This single sentence is what graders look for — without it, "AI-powered" claims get penalized per the spec's explicit warning. |
| **Business/operational problem** | ✅ Done well — README "The Problem" section quantifies it: *"4–6 hours/week, wrong 40% of the time, costs $15,000–60,000/year."* This is exactly the kind of quantification the spec rewards. | — |
| **The decision being automated/augmented** | ✅ Clear — the weekly HOLD/MARKDOWN/PROMOTE/CLEAR pricing decision (README "The 4 Decisions"). | — |
| **Why a non-AI baseline is insufficient** | 🟡 Implicit (manual process is slow/error-prone) but **not explicitly contrasted with your own rules-only baseline**. | You *have* the comparison material — see next row. Write it up. |
| **Who would realistically deploy/pay** | ✅ Done — "small Adidas single-brand retailers... 150–500 products" is concrete and specific (this is exactly what graders mean by "who would realistically pay," as opposed to vague "businesses"). | — |
| **At least one explicit non-AI baseline** | 🟡 Exists in code (`services/decision_intelligence/training/baseline.py`, plus the StylePulse rules engine that drives the dashboard list) but is **not documented or benchmarked**. | **Run rules-only vs. CatBoost head-to-head on the real test set and publish a table** (accuracy/macro-F1, plus where the model adds value the rules don't). You already have the harness (`evaluation/edge_case_benchmark.py`). This is a quick, high-value win — the comparison numbers essentially write your "why AI" justification for you. |
| **Quantitative/qualitative justification for the AI approach** | 🟡 Partial — the model's real-test accuracy (96.5%) and SHAP explainability exist, but they aren't framed as "why AI beats the rules-only baseline." | Same fix as above — once you have the head-to-head table, the justification follows directly: *"the rules baseline catches X% of correct decisions; CatCatBoost + rules catches Y%, primarily by [specific mechanism, e.g., weighting competitor price-gap + seasonality jointly]."* |

**Verdict on §3.1:** You have *all the raw material* to satisfy this section completely — it's
sitting in your code and your README's problem statement. The two specific gaps (explicit
novelty sentence + baseline benchmark table) are writing tasks, not engineering tasks. Do
both before submission; "vague AI-powered claims... will be penalized" is stated explicitly
in the spec.

### 4.2 — Research-Oriented Projects (§3.2)

Not applicable — you're application-oriented, and correctly so (your project is squarely a
deployable business system, not a publishable research contribution). No action needed; just
don't accidentally frame anything as "research" in your docs/demo, since that would trigger
the (much stricter) research rubric instead.

---

## 5. Section 4 — System Architecture Requirements

### 5.1 — Service Boundary and Responsibilities (§4.1)

> "External Endpoint (EEP)... At least two Internal Endpoints (IEPs)... A monolith... will be penalized unless you justify the decision."

**What you did:** You have **one EEP + three IEPs** — exceeding the "at least two IEPs"
minimum:
- **EEP** — `eep/main.py` (FastAPI, public boundary, auth, orchestration)
- **IE1** — `services/market_intelligence` (competitor/seasonality signal extraction)
- **IE2** — `services/decision_intelligence` (CatBoost + rules pricing-decision engine)
- **IE3** — `services/campaign_creative` (LLM-based campaign copy generation)

**What's missing/weak:** None structurally. One thing to be ready to defend: the EEP also
imports and calls IE2's recommendation function **in-process** (not purely over HTTP) for the
synchronous hot path, while IE2 also runs as its own deployable service. This is *exactly*
the kind of "did you justify it" moment the spec calls out — and you now have it justified
with numbers in **Tradeoff #3** of `docs/TRADEOFFS.md`. Make sure whoever presents knows this
tradeoff cold; it's a near-certain Q&A question ("why does your EEP import your IEP's code
directly?").

### 5.2 — Internal Endpoints (§4.2)

> "Each must be architecturally independent... serve a clearly motivated role... contain non-trivial modeling or logic... expose a clear input-output contract... defined error/fallback behavior. Near-identical endpoints will be penalized."

| Requirement | IE1 (market_intelligence) | IE2 (decision_intelligence) | IE3 (campaign_creative) |
|---|---|---|---|
| Architecturally independent | ✅ Separate service + Dockerfile | ✅ Separate service + Dockerfile, runs standalone on `:8002` | ✅ Separate service + Dockerfile |
| Clearly motivated, distinct role | ✅ Competitor price + seasonality signal extraction — clearly different from IE2/IE3 | ✅ CatBoost-based pricing decisions with SHAP explainability — the core "AI depth" of the system | ✅ LLM-generated campaign copy (Instagram/Facebook/Telegram) — clearly different again |
| Non-trivial logic | ✅ Multi-source scraping + Adidas seasonal calendar engine | ✅✅ Trained CatBoost model, feature engineering, hard-rule gating, confidence calibration, SHAP — this is your strongest IEP | ✅ Prompt-engineered LLM pipeline with structured output and tone control |
| Clear I/O contract | 🟡 Likely yes (FastAPI + Pydantic), **not confirmed to have `/metrics` exposure** | ✅ Documented, instrumented, has `/metrics` | 🟡 Likely yes, **not confirmed to have `/metrics` exposure** |
| Error/fallback behavior | 🟡 Has timeouts from EEP side; **no documented retry/circuit-breaker, no dedicated fallback if it's down** | ✅ Confidence-gated fallback to `HOLD` (your Tradeoff #1) | 🟡 Same — needs documented fallback (e.g., "skip campaign generation, surface a 'creative unavailable' state") |
| Near-identical to others? | No — distinct | No — distinct | No — distinct |

**Verdict:** Your three IEPs are genuinely distinct (this is explicitly praised — "near-identical
endpoints will be penalized," and yours clearly aren't). The gap is **uniformity of
instrumentation and documented failure behavior across all three**, not the core logic
itself. Close this in §11 and §12 below.

### 5.3 — External Endpoint (§4.3)

> "Must use FastAPI (or equivalent)... orchestrate multiple internal endpoints... support conditional and/or parallel model interaction... enforce input validation, constraints, and request limits. Thin pass-through APIs are insufficient."

| Requirement | Status | Evidence / Gap |
|---|---|---|
| FastAPI implementation | ✅ | `eep/main.py` |
| Orchestrates multiple IEPs | ✅ | EEP calls IE1/IE2/IE3 (`eep/apify_ingest.py`, `eep/frontend_bridge.py`, in-process IE2 call, etc.) |
| Conditional/parallel model interaction | 🟡 Likely (confidence gating = conditional logic), **not explicitly demonstrated as "parallel"** | If you do call IEPs in parallel anywhere (e.g., fan-out to IE1 + IE3 for a campaign), call this out explicitly in your docs/demo — it's a specific thing graders are told to look for. If you don't currently do it anywhere, consider whether one natural place exists (e.g., fetching market signals and generating creative copy concurrently) and whether it's worth adding before the deadline. |
| Input validation + constraints + request limits | 🟡 Partial | Pydantic validation ✅ exists. **Rate limiting / request limits do not exist on the EEP** — this is also explicitly required again in §12 (see below); it's the same gap counted twice in the spec, so fixing it once satisfies both. |
| Not a thin pass-through | ✅ | EEP does real orchestration, auth, multi-tenancy, business logic — far from "thin." |

---

## 6. Section 5 — Explicit Tradeoff Documentation

> "You must include a section... titled **Tradeoffs**, containing at least: 3 engineering tradeoffs... what you chose and why... what you did **not** choose and why... evidence (measurements, benchmarks, experiments)."

**Status: ✅ Now satisfied.** This section **did not exist** before this session — the prior
gap analysis (`docs/PROJECT_GAP_ANALYSIS.md`) flagged it as the single highest-priority
missing item ("Not written... Required — penalized if absent").

I wrote `docs/TRADEOFFS.md` for you, containing **4 tradeoffs** (one more than required), each
with a "what we chose / what we rejected / why / evidence" structure and **real numbers
pulled directly from your own model metadata** (`meta.json`):

1. **Rule-gated CatBoost vs. pure ML** — evidence: `CLEAR` recall = 1.00 on validation but
   collapses to **0.017** on your adversarial stress set.
2. **Heuristic (`ai_label`) training labels vs. waiting for real outcomes** — evidence:
   validation accuracy 0.998 vs. real-test accuracy 0.965 (quantifies the label-circularity
   gap).
3. **In-process IE2 call vs. pure microservice topology** — evidence: latency/RAM tradeoff
   on your constrained Lightsail box, plus the documented "list-vs-drawer" reconciliation
   cost.
4. **Daily batch Apify scraping vs. real-time polling** — evidence: large accumulated
   snapshot volume at predictable cost vs. ≤24h staleness, mitigated by the
   `data_freshness_hours` confidence-decay signal.

**What's left for you to do:** read it, adjust the tone/wording to your voice, verify the
numbers against your latest `meta.json` if the model has been retrained since, and **link it
from the README** so graders find it immediately.

---

## 7. Section 6 — Git Discipline and Traceability

> "Meaningful commit history (no 'final commit' repositories)... Feature-based branching... Clear ownership and review discipline (PRs, code review notes)... Prompt versions must be tracked and justified with evaluation evidence."

| Requirement | What you did | What's missing |
|---|---|---|
| Meaningful commit history | ✅ — `git log` shows 20+ substantive, descriptively-named commits (e.g., "Fix inventory import price column," "Add production CI/CD deployment," "adding admin role for the financial, closed loop tracking and recommender assistant"). Not a "final commit" repo. | — |
| Feature-based branching | 🟡 Partial — `main`, `dev`, `qa` branches exist remotely. | This is **environment-based** branching (dev/qa/main), not clearly **feature**-based. The spec wants to see topic/feature branches that get merged via review, not just promotion lanes. Consider creating a couple of short-lived feature branches for your remaining work items (e.g., `feature/ie1-ie3-metrics`, `feature/rate-limiting`) and merging them via PR — even self-reviewed PRs create the "review discipline" trail the rubric is checking for. |
| Clear ownership / review discipline (PRs, review notes) | ❌ Not visible | No PR/review trail found (no `gh` access in this environment to confirm definitively, but commits land directly on `dev` via merges from `dev` into `dev`, suggesting no PR workflow). **Open at least a few PRs for your remaining changes and leave review comments** — even between teammates reviewing each other's work for 5 minutes. This is graded explicitly (G2: "Branching, review, traceability" = 2.5%). |
| LLM prompt versions tracked + justified with eval evidence | 🟡 Weak | IE3 has a static `prompt_version="v1.0"` constant in code (`services/campaign_creative`), but there's **no version history and no evaluation evidence tying prompt changes to measured improvements**. Move prompts to a versioned file/table, bump the version on every meaningful change, and record a before/after comparison on your IE3 golden set each time you do. |

---

## 8. Section 7 — MLOps and LLMOps

> "At least one automated pipeline covering: training/updating, evaluation, deployment/promotion/rollback. Required: experiment tracking, explicit metrics and thresholds, decision logic for model selection and promotion. Static systems... will score poorly."

**What you did — this is one of your strongest areas:**
- **Experiment tracking:** MLflow with **54 logged trials** (`mlflow.db`, `mlartifacts/`),
  full metrics per trial.
- **Training:** `services/decision_intelligence/training/train.py` (+ `baseline.py`,
  `register_model.py`).
- **Evaluation:** `evaluation/promote.py`, `evaluation/edge_case_benchmark.py`, golden
  scenarios, plus a documented `meta.json` with per-trial thresholds and a held-out
  **stress test** set — genuinely rigorous, beyond what most student projects do.
- **Decision logic exists in code:** `meta.json.best_trial` selection, promotion gating in
  `promote.py`.

**What's missing:**
- **"One automated pipeline" — currently it's manual scripts, run by hand, not a single
  wired pipeline.** The spec is explicit: "static systems without lifecycle logic will score
  poorly." You have all the *components* of an automated lifecycle (train → eval → promote)
  but they aren't yet **chained into one runnable thing** (a Make target, a script, or — best
  — a CI job triggered on a schedule or on new-data arrival) that goes train → evaluate
  against thresholds + golden/edge cases → **promote only if it beats the current champion**
  → otherwise no-op/rollback. This is the highest-value MLOps fix: you're 80% there, and the
  remaining 20% (wiring, not building) is what the rubric actually scores.
- **Document the promotion thresholds and decision logic explicitly** — e.g., *"promote
  candidate iff real-test macro-F1 ≥ champion's AND no regression on the golden set AND
  stress-set `CLEAR` precision stays ≥ X."* Right now this logic lives in code; it needs to
  also live in a doc a non-engineer grader can read.
- **Model versioning clarity:** the gap analysis notes the health endpoint reports
  `retail_radar_decision_model_v6` while `meta.json.best_trial` points elsewhere — pin one
  source of truth and have the running service log exactly which artifact is live. This
  matters for the "rollback decision" requirement — you can't roll back to a version you
  can't unambiguously identify.

---

## 9. Section 8 — Quality Assurance and Reliability (Non-Negotiable)

### 9.1 — Test Suite (§8.1)

> "Unit tests. Integration tests across services. At least one end-to-end test that calls the deployed system. Hard rule: if the system fails during the demo, grading stops."

| Requirement | Status | Evidence / Gap |
|---|---|---|
| Unit tests | ✅ | `tests/unit/` — 14 files covering apify ingest, campaign creative, competitor matching/processing, features, inventory tenant isolation, RDS reads, rules, scraping, etc. |
| Integration tests across services | ✅ | `tests/integration/` — `test_eep_pipeline.py`, `test_ie2_model.py`, `test_promote_pipeline.py`, plus a `golden/` scenario directory. |
| **End-to-end test that calls the deployed system** | ❌ **Missing** | There is no `tests/e2e/` directory and no test that hits the **public** `retailradar.site` URL. This is explicitly flagged as required and is your single biggest QA risk: the rubric's hard rule — *"if the system fails during the demo, grading stops"* — exists precisely because graders will hit your live URL. **Add a script that logs in, fetches a report, requests a recommendation, and asserts the response shape against the live deployment**, and run it as a pre-demo smoke check (and ideally as a post-deploy CI gate). This is the #1 thing to do before submission. |

### 9.2 — Evaluation and Regression Protection (§8.2)

> "At least one of: offline regression tests, golden dataset tests, data validation checks. If you use LLM components, define how you test them despite non-determinism."

| Requirement | Status | Evidence |
|---|---|---|
| Golden dataset tests | ✅ | `tests/integration/golden/` — fixed scenarios with expected decisions. |
| Offline regression / model-version comparison | ✅ | `evaluation/edge_case_benchmark.py`, `model_only_edge_case_benchmark.py`, the stress-test split in `meta.json`. |
| Data validation (schema, ranges, drift) | ✅ | Schema validation referenced in the gap analysis; `data_freshness_hours` acts as a drift-style proxy. |
| **LLM non-determinism testing strategy — documented** | ❌ **Missing as a written artifact** | The spec doesn't just want you to *handle* this — it wants you to **define and document how**. You likely already do something sensible informally (structural/schema checks on IE3 output, perhaps banned-content checks). Write a short `docs/TESTING.md` (or a section in an existing doc) stating explicitly: *"LLM outputs are tested via (a) JSON-schema/structural assertions, (b) banned-content filters, (c) a tolerance-banded golden set scored on semantic similarity rather than exact string match — because exact-match assertions are meaningless against a non-deterministic generator."* This is a 30-minute writing task that closes a named, explicit requirement. |

**Verdict:** You comfortably clear the "at least one" bar for §8.2 (you actually have all
three). The two real gaps in this whole section are (1) the missing live E2E test and (2) the
missing *written* LLM-testing rationale — both are the kind of "you did the work but didn't
make it visible" gaps the spec repeatedly warns about ("must make visible and defensible").

---

## 10. Section 9 — Containerization and Deployment

> "At least three Docker images: IE1, IE2, EEP. Docker Compose and Kubernetes are required."

**Status: ✅ Comfortably exceeded.**
- **6 application Dockerfiles** found: `eep/Dockerfile`, `frontend/Dockerfile`,
  `services/market_intelligence/Dockerfile`, `services/decision_intelligence/Dockerfile`,
  `services/campaign_creative/Dockerfile`, `services/telegram_assistant/Dockerfile` — well
  past the 3-image minimum (and that's not even counting the 7 Apify actor Dockerfiles).
- **Docker Compose:** multiple compose files in `infra/` (`docker-compose.yml`,
  `docker-compose.local.yml`, `docker-compose.aws.yml`, `docker-compose.eep.yml`).
- **Kubernetes:** full manifest set in `infra/k8s/` (namespace, config, PgBouncer, backends,
  frontend/telegram, ingress, monitoring, load-balancer proxy, kustomization) — this is a
  genuinely complete k8s setup, not a token gesture.

**Minor cleanup item (not a rubric point, but affects "engineering maturity" perception):**
the gap analysis notes ~138MB of unused `trial_*.cbm` model artifacts ship inside the
IE2/EEP images. Add them to `.dockerignore` — smaller images = faster deploys = a small but
visible signal of operational care.

---

## 11. Section 10 — Cloud Deployment

> "Deployed on AWS/Azure/GCP/other, publicly accessible, fully functional end-to-end. Must document: deployment architecture, secrets management, cost estimate and cost drivers."

| Requirement | Status | Notes |
|---|---|---|
| Deployed on a public cloud | ✅ | AWS (Lightsail + RDS), per `docs/aws-rds-apify-webhook.md`, `docs/full-stack-docker-deployment.md`, `docs/KUBERNETES_DEPLOYMENT.md`. |
| Publicly accessible API | ✅ | `retailradar.site` — verified via the screenshot you shared this session (live admin dashboard). |
| Fully functional end-to-end | ⚠️ Probably, **but not proven by an automated check** | Same root cause as §8.1 — you need a scripted E2E proof, not just "it looked fine when I clicked through it." |
| **Deployment architecture documented** | 🟡 Thin / scattered | You have several deployment docs (`docs/full-stack-docker-deployment.md`, `docs/KUBERNETES_DEPLOYMENT.md`, `docs/aws-rds-apify-webhook.md`) but **no single consolidated architecture doc with a diagram** that a grader can read in 5 minutes. |
| **Secrets management documented** | ❌ Missing as a stated *approach*, and weak in practice | Currently a flat `.env` with live secrets (RDS password, `APIFY_TOKEN`, `APIFY_WEBHOOK_SECRET`), and `AUTH_TOKEN_SECRET`/admin password are still **placeholder values**. The spec wants you to *document the approach* — and right now the honest documentation would be "we don't really have one yet," which is a problem. **Rotate the exposed secrets, set real values for the placeholders, move to k8s `Secret` objects (you already have the manifests in `infra/k8s/00-config.yaml` to extend), and write down the approach + a rotation policy** — even a simple one. This is both a §10 documentation requirement *and* a real security exposure (your `.env` is currently open in your editor with live credentials — be careful what you screenshot/share). |
| **Cost estimate + cost drivers documented** | ❌ Missing | Write a small table: RDS instance class + monthly cost, Lightsail plan, Apify plan (scrape volume × price), LLM API cost (Anthropic per-1k-tokens × estimated monthly call volume), egress. Identify the dominant driver (likely Apify scraping or LLM calls) — this single paragraph is what the spec is asking for, and it doubles as material for your Tradeoffs doc (cost vs. freshness, cost vs. quality). |

**Recommended action:** consolidate the above into one new doc,
`docs/DEPLOYMENT_ARCHITECTURE.md` — architecture diagram (even a simple boxes-and-arrows one),
secrets approach + rotation policy, and the cost table. This single doc closes three named
requirements at once.

---

## 12. Section 11 — Monitoring and Observability

> "Prometheus (or equivalent). Grafana (or equivalent). At least one meaningful metric per service: latency (p50/p95), error rate by class, throughput. If model inference: at least one ML-specific signal (confidence stats, input drift proxy, output distribution shift)."

| Requirement | Status | Notes |
|---|---|---|
| Prometheus | ✅ | `infra/monitoring/prometheus.yml`, k8s manifest `50-monitoring.yaml`. |
| Grafana | ✅ | Dashboards exist (`stylepulse-eep`, `live-rds-evaluation` per the gap analysis). |
| **Per-service metrics — EEP** | ✅ | `eep/observability.py` — instrumented. |
| **Per-service metrics — IE2** | ✅ | `services/decision_intelligence/main.py` exposes `/metrics` with decision/fallback counters and the confidence gauge. |
| **Per-service metrics — IE1** | ❌ **Missing** | No `/metrics` endpoint found in `services/market_intelligence`. |
| **Per-service metrics — IE3** | ❌ **Missing** | No `/metrics` endpoint found in `services/campaign_creative`. |
| Latency p50/p95, error rate by class, throughput — *for all 4 services* | 🟡 Partial | Present for EEP/IE2; **absent for IE1/IE3 because they have no `/metrics` at all**. |
| ML-specific signal | ✅ | `ie2_avg_confidence` gauge + live-RDS evaluation metrics. Consider also adding an explicit **input-drift proxy** (e.g., a rolling distribution of `price_gap_pct` or `data_freshness_hours`) — you already compute these values, so exposing them as a Prometheus gauge is a small addition that directly satisfies "input drift proxy / output distribution shift." |

**This is your most concrete, mechanical remaining gap.** Add
`prometheus-fastapi-instrumentator` (or `make_asgi_app`) to IE1 and IE3 — the same pattern you
already used for EEP/IE2 — and extend your Grafana dashboards with panels for all four
services. This is probably a half-day of work and it closes a "Required" line item that's
currently failing outright for two of your four services.

---

## 13. Section 12 — Security and Robustness (Minimum Standard)

> "Input validation and payload constraints. Basic abuse resistance (rate limits or equivalent). Clear failure mode behavior (timeouts, retries, fallbacks)."

| Requirement | Status | Notes |
|---|---|---|
| Input validation + payload constraints | ✅ | Pydantic models throughout the EEP and IEPs. |
| **Basic abuse resistance (rate limiting)** | ❌ **Missing on the public-facing system** | Only `services/telegram_assistant/app.py` has rate limiting. The EEP — your actual public API boundary — has **none**. Add `slowapi` (FastAPI-native) or an ingress/Caddy-level limit on at least `/auth/*`, `/recommend/*`, and the Apify webhook endpoint. This is named explicitly *twice* in the spec (§4.3 "request limits" and §12 "rate limits") — fixing it once satisfies both. |
| Clear failure-mode behavior (timeouts, retries, fallbacks) | 🟡 Partial | EEP→IE calls have **timeouts** ✅ and IE2 has a documented confidence-gated **fallback to HOLD** ✅ (this is genuinely good — it's your Tradeoff #1). But there are **no retries or circuit breakers** anywhere, and **IE1/IE3 have no documented fallback if they're unreachable** (e.g., what does the EEP do if IE3 — the campaign generator — times out? Does the user see an error, a stale result, or a graceful "creative unavailable" state?). Add bounded retries (2–3 attempts with backoff) for transient failures, and explicitly define + document the fallback for each IEP being down. |

**Side note on what I observed this session:** your `.env` file is currently open in your
editor and contains live secrets (per the project memory: exposed RDS password, `APIFY_TOKEN`,
`APIFY_WEBHOOK_SECRET`, placeholder `AUTH_TOKEN_SECRET`/admin password). This isn't a rubric
line item per se, but it **is** the kind of thing that turns "secrets management" from a
documentation exercise into a real finding if a grader (or anyone) sees your screen. Rotate
these before the demo regardless of what you decide to document.

---

## 14. Section 13 — Dynamic and Competitive Grading

> "Projects are ranked relative to peers... feature count does not outweigh robustness, clarity, and engineering maturity."

No specific action item — this section just tells you *how* you'll be graded once the
baseline is met. Your relative position will be determined by exactly the kind of polish
items listed above (visible tradeoffs, uniform observability, documented failure modes,
proven E2E reliability) — **not** by adding more features. If you're choosing where to spend
remaining time, prioritize *finishing and proving* what exists over building anything new.

---

## 15. Section 14 — Final Deliverables

> "A clean GitHub repository. A working cloud deployment. A live demo. Technical and business documentation. You will be questioned on design decisions, failure modes, and tradeoffs."

| Deliverable | Status | Notes |
|---|---|---|
| Clean GitHub repo | 🟡 | Commit history is meaningful (✅), but consider a final pass to remove stray artifacts (e.g., `test_gpt_image.png`, `test_image.png`, `stylepulseai_new.docx`, `catboost_info/` at repo root, `mlflow.db`/`mlartifacts` if they're large/binary) — "clean" includes "doesn't ship test scratch files at the repo root." |
| Working cloud deployment | ✅ | Confirmed live this session. |
| Live demo | ⚠️ | Will be judged live — make sure the **scripted E2E walkthrough** (§8.1/§9) doubles as your demo rehearsal script, so you've proven the golden path works end-to-end before you're standing in front of graders. |
| Technical and business documentation | 🟡 | Strong technical docs exist (`docs/*.md`, README). **Business documentation is thinner** — the README's "Problem/Solution" section is good business framing, but there's no dedicated business doc covering market sizing, "who pays and how much," competitive landscape, or go-to-market — all things the Q&A ("who would realistically deploy or pay for this," from §3.1) will probe. |
| Be ready to be questioned on design decisions, failure modes, tradeoffs | 🟡 | `docs/TRADEOFFS.md` (now written) gives you a script for the tradeoffs questions. **Rehearse the in-process-IE2 justification, the heuristic-label gap, and the rule-gating rationale out loud** — these are your most "interesting" (i.e., most likely to be probed) decisions, and you now have the numbers to back each one. |

---

## 16. Mapping to the Scored Rubric Categories

The assessment template scores you across nine weighted categories. Here's how the gaps
above map onto graded line items (so you can prioritize by points-at-risk, not just by
spec-section order):

| Category | Weight | Items at risk from gaps above |
|---|---|---|
| **T — AI Technical Complexity (30%)** | T1 (depth/non-triviality 5%), T5 (tradeoff evidence 5%), T6 (execution quality/edge cases 5%) | T5 was at serious risk (no Tradeoffs doc) — **now mitigated**. T6 benefits from the live E2E test and the documented IE1/IE3 fallback behavior. T1 is already strong (CatBoost+SHAP+rules is genuinely non-trivial) — just make sure your demo *foregrounds* this over the LLM-copy IEP. |
| **S — Software Methodology (15%)** | S2 (validation/constraints 3%), S3 (errors/timeouts/retries/fallbacks 3%), S5 (deployment architecture/secrets 3%) | S2/S3 directly hit by the missing rate limiting and missing retry/fallback documentation for IE1/IE3. S5 hit by the thin secrets/cost documentation. |
| **P — Positioning (10%)** | P1 (problem clarity 2.5%), P3 (AI justification 2.5%) | P1 is strong already. P3 is the one at risk — **the missing baseline-vs-model benchmark table is exactly what P3 ("AI justification/contribution") scores on.** This is your highest-value writing task in the whole review. |
| **Q — Quality Assurance (5%)** | Q1 (test breadth 2.5%), Q2 (regression strategy 2.5%) | Q1 is at risk specifically because of the missing **deployed-system E2E test** — the spec calls this out as a named, separate requirement from unit/integration. Q2 is solid (golden + edge-case + stress sets). |
| **G — GitHub (5%)** | G1 (commit history/ownership 2.5%), G2 (branching/review/traceability 2.5%) | G1 is solid. G2 is at risk — environment branches (dev/qa/main) aren't the same as feature branches with PR review, which is what's explicitly named. |
| **M — MLOps/Observability/Docs (10%)** | M1 (automated lifecycle pipeline 2.5%), M2 (experiment tracking/thresholds 2.5%), M3 (monitoring/ML signals 2.5%), M4 (documentation completeness 2.5%) | M2 is your strongest line item here (54 MLflow trials, real thresholds). M1 is at risk — pipeline exists as scripts, not as one wired automated flow. M3 is partially at risk — IE1/IE3 have no metrics. M4 benefits directly from the new Tradeoffs doc plus the deployment-architecture/secrets/cost doc you still need to write. |

---

## 17. Prioritized Action List (highest grade-impact first)

1. **Add a scripted E2E test against the live deployed URL** (`retailradar.site`) — closes
   GT1's risk, Q1, and §8.1's hard rule in one shot. Highest priority; this is the one item
   the spec says can stop grading entirely if it fails live.
2. **Add rate limiting to the EEP** — closes both §4.3 and §12 simultaneously (named twice in
   the spec). A `slowapi` middleware on `/auth/*`, `/recommend/*`, and the webhook is a
   half-day task.
3. **Add `/metrics` to IE1 and IE3** + extend Grafana — closes §11's "per-service metrics"
   requirement, which currently fails for half your services.
4. **Write the rules-vs-CatBoost baseline benchmark table** — closes §3.1's "non-AI baseline"
   requirement *and* directly feeds P3 ("AI justification/contribution," 2.5% on its own).
   You already have the harness; this is mostly a "run it and write it up" task.
5. **Rotate exposed secrets, write `docs/DEPLOYMENT_ARCHITECTURE.md`** (diagram + secrets
   approach + cost table) — closes three named §10 requirements and removes a live
   security exposure.
6. **Add bounded retries + documented fallback behavior for IE1/IE3 being down** — closes the
   remaining half of §12's "failure mode behavior" requirement.
7. **Open a few feature-branch PRs (even self-reviewed) for your remaining work, and write
   down the LLM prompt-versioning history with eval evidence** — closes G2 and the §6 prompt
   requirement.
8. **Write `docs/TESTING.md`** describing your LLM non-determinism testing approach — a
   30-minute task that closes a named §8.2 requirement.
9. **Wire train→eval→promote into one runnable pipeline** (script or CI job) with documented
   promotion thresholds — closes §7's "automated lifecycle" requirement; you're closest to
   done here, this is wiring, not building.
10. **Add an explicit novelty-claim sentence to the README**, link `docs/TRADEOFFS.md` from
    it, and do a final repo cleanup pass (remove stray test images/scratch files at root).

Items 1–5 are the ones most likely to move your score; items 6–10 are the "engineering
maturity" polish that separates a strong project from an exceptional one in a competitive
cohort (§13).
