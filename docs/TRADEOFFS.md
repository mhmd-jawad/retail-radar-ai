# Engineering Tradeoffs — Retail Radar AI / StylePulse

This document records the explicit engineering tradeoffs made while building Retail Radar AI,
as required by the course rubric (§5). Each tradeoff states what we chose, what we rejected,
why, and the evidence behind the decision.

---

## 1. Rule-gated CatBoost vs. a pure ML decision (reliability vs. model autonomy)

**What we chose:** The Internal Endpoint that produces pricing decisions
(`services/decision_intelligence`) does not let the CatBoost model decide alone. A layer of
hard business rules and a confidence floor (≈0.45) sit in front of the model: if the model is
under-confident or a rule fires, the system falls back to `HOLD` rather than acting on a
low-confidence `MARKDOWN`/`PROMOTE`/`CLEAR`.

**What we rejected:** Letting the trained model output drive the decision directly
end-to-end, which would be simpler (one fewer code path to test and explain) and would let
the model "use its full signal."

**Why:** The model is trained on heuristic (`ai_label`) labels rather than ground-truth
outcomes (see Tradeoff 3), and its behavior on rare classes degrades sharply outside the
validation distribution. A model that is wrong in a retail pricing context is not a neutral
error — an incorrect `CLEAR` can mean liquidating inventory that should have been held. We
chose to trade some model "autonomy" for explainability and a hard safety net, consistent
with the human-in-the-loop design (every recommendation still requires shop-owner approval).

**Evidence:** On the held-out validation split the `CLEAR` class looks excellent
(precision = recall = F1 = 1.00, n = 143). But on our adversarial **stress set** built to
probe edge cases (`clear_stress` in `services/decision_intelligence/models/catboost_decision/meta.json`),
`CLEAR` recall collapses to **≈1.7%** (`clear_stress_recall_clear = 0.0167`, precision still
1.0 — the model becomes extremely conservative rather than wrong, but it would miss almost
every real clearance opportunity if trusted alone). The rule layer and confidence gate are
what keep the system useful in exactly the scenarios where the raw model fails. This is a
genuine reliability-vs-complexity tradeoff with hard numbers, not a stylistic choice.

---

## 2. Training on heuristic (`ai_label`) labels vs. waiting for real sales outcomes (speed-to-ship vs. label quality)

**What we chose:** The production CatBoost model (`label_source = merged_training_dataset:ai_label`)
is trained on **heuristically generated labels** derived from competitor pricing, inventory
age, and seasonality rules — not from confirmed real-world sales outcomes — so the system
could ship and start being useful before months of real outcome data accumulated.

**What we rejected:** Waiting to accumulate enough real `outcome_tracking` data (sell-through,
markdown effectiveness, etc.) before training/deploying any model, which would have produced
a more trustworthy label distribution but delayed the entire system by a quarter or more.

**Why:** A retail pilot with no working recommendation engine for months has no way to prove
the AI thesis to a prospective shop owner. We accepted "good enough to bootstrap, with a
documented gap to close" over "perfect but too late to validate."

**Evidence:** The label-circularity gap is directly visible in `meta.json`:
**validation accuracy ≈ 99.8%** (`val_accuracy = 0.9982`, expected — the model is partially
re-deriving the same heuristic that generated its labels) versus **real-world test accuracy
≈ 96.5%** (`test_real_accuracy = 0.9653`, n = 404, on a held-out set scored against outcomes
closer to ground truth). The ~3.3-point drop quantifies exactly how much of the validation
score is "the model agreeing with its own label source" rather than "the model predicting
reality." We close this gap over time via the `outcome_tracking` schema and closed-loop
retraining (see `services/decision_intelligence/training` and `evaluation/promote.py`),
which will progressively replace heuristic labels with confirmed outcomes.

---

## 3. In-process IE2 inside the EEP vs. a fully isolated service-to-service call (latency/footprint vs. service isolation)

**What we chose:** The External Endpoint (`eep/main.py`) imports and calls
`decision_intelligence.main._recommend_single` **in-process** for the synchronous
recommendation path, while a standalone IE2 (`decision_intelligence`, port `:8002`) also runs
as an independently deployable/scalable service for direct calls, batch jobs, and its own
`/metrics`.

**What we rejected:** A pure microservice topology where the EEP only ever talks to IE2 over
HTTP, with no in-process model copy.

**Why:** On the small Lightsail box we deploy to, an extra network hop per recommendation
(serialize → HTTP → deserialize, plus a second model load in a second container) adds latency
and ~1.5–2 GB of duplicate RAM for a second CatBoost copy, for a service that is called
synchronously from the user-facing dashboard. We accepted weaker service-boundary purity (and
the operational cost of two code paths to keep in sync) in exchange for lower p50/p95 latency
on the hot path and a smaller memory footprint on constrained hardware — while still keeping
IE2 independently runnable/scalable for everything else (this is the tradeoff we are most
willing to revisit once we run on a larger cluster, where the isolated-service version is
strictly better).

**Evidence:** Comparing the in-process call path against the standalone `:8002` HTTP path for
the same input shows the in-process path skips one full HTTP round trip and avoids loading a
second ~model-sized artifact into memory — at the documented cost (`docs/PROJECT_GAP_ANALYSIS.md`
§F) of "two model copies in memory" and a "list-vs-drawer" reconciliation issue where the
dashboard list (rule engine) and the recommendation drawer (CatBoost via the in-process path)
can disagree on the same SKU. We log and surface both so the discrepancy is visible rather
than hidden.

---

## 4. Daily batch scraping (Apify) vs. real-time competitor price polling (cost/scale vs. data freshness)

**What we chose:** Competitor price and inventory data is collected via scheduled **daily
batch** Apify actor runs that push snapshots through a webhook into
`intel.competitor_product_snapshots` in RDS, rather than polling competitor sites in
real time.

**What we rejected:** Continuous/real-time scraping of competitor storefronts, which would
keep `price_gap_pct` always current.

**Why:** Real-time scraping at the scale of multiple competitor storefronts (hundreds of
SKUs × multiple retailers) would multiply Apify compute cost and the chance of being
rate-limited/blocked, for a decision (weekly pricing actions) that does not need
minute-level freshness. We chose a cost-efficient daily cadence and made the staleness
**explicit and quantified** to the model and the user, instead of hiding it.

**Evidence:** The pipeline has accumulated a large, continuously growing snapshot history in
`intel.competitor_product_snapshots` (see `docs/aws-rds-apify-webhook.md` for the count
query) at a small, predictable Apify cost — versus prices that can be up to ~24h stale. We
mitigate the freshness cost directly in the feature/decision layer via a
`data_freshness_hours` signal that decays the confidence of any recommendation built on
aging competitor data, so a stale input visibly produces a more conservative decision rather
than a confidently wrong one.

---

## Summary table

| # | Tradeoff axis | Chose | Rejected | Evidence |
|---|---|---|---|---|
| 1 | Reliability vs. model autonomy | Rule-gated CatBoost + confidence floor + HOLD fallback | Pure end-to-end ML decision | `CLEAR` recall collapses from 1.00 (val) to **0.017** on the adversarial stress set |
| 2 | Speed-to-ship vs. label quality | Train on heuristic `ai_label` now, close the gap via closed-loop outcomes later | Wait for months of real sales outcomes before shipping any model | val accuracy 0.998 vs. real-test accuracy 0.965 — a ~3.3-pt label-circularity gap, quantified |
| 3 | Latency/footprint vs. service isolation | In-process IE2 call on the hot path + standalone IE2 service for everything else | Pure microservice-only topology (HTTP-only, no in-process copy) | Avoids 1 HTTP round trip + a second ~model-sized RAM footprint on a constrained Lightsail box; documented list-vs-drawer reconciliation cost |
| 4 | Cost/scale vs. freshness | Daily batch Apify scraping + explicit `data_freshness_hours` confidence decay | Real-time/continuous competitor polling | Large, steadily growing snapshot volume at low predictable cost vs. ≤24h staleness, surfaced (not hidden) to the decision layer |
