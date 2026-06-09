# Human Validation Layer

A final **human-review stage** that runs *after* the system recommendation is generated. It lets a
reviewer **accept**, **override**, or **reject** the system's HOLD/MARKDOWN/PROMOTE/CLEAR decision,
and persists everything needed to use those human decisions as **ground-truth labels for retraining
and evaluation** — without ever modifying the system recommendation itself.

> **The recommendation logic is unchanged.** IE2 (`services/decision_intelligence`) still produces
> the decision exactly as before. This layer only records what a human did with it.

---

## 1. Why this exists

The decision pipeline already persists the system recommendation **with full context**:

- `marketing.system_decision_latest` — `recommendation`, `confidence`, `model_version`,
  `rule_override`, `fallback_used`, `requires_human_approval`, and the JSONB blobs
  `input_context`, `competitor_signals`, `decision_payload` (the exact features fed to the model).
- `marketing.recommendations` — SHAP feature breakdown (`shap_features_json`), rule-override detail,
  `model_version`, `explanation`.

What was **missing**: the human review never reached the backend. The dashboard's
`RecommendationDrawer` approve/reject buttons only mutated local browser state and toasted *"logged
to audit trail"* — nothing was stored, so there were no ground-truth labels, no acceptance/override
metrics, and no audit trail of who decided what.

This layer closes that gap.

---

## 2. Data model (`infra/postgres/008_human_validation.sql`)

Additive and idempotent. Auto-applies on first DB connect through
`eep/retail_db.py::_ensure_additive_schema` (it is listed in `ADDITIVE_SCHEMA_PATHS`) — **no manual
migration step** on the live RDS.

### `marketing.recommendation_reviews` (one current review per SKU per tenant)

| Group | Columns | Notes |
|---|---|---|
| Keys | `id`, `tenant_id`, `sku_id`, `variant_id`, `recommendation_id`, `system_decision_run_id` | tenant-isolated; `unique (tenant_id, sku_id)` |
| **System snapshot (frozen)** | `system_recommendation`, `system_confidence`, `system_suggested_price_usd`, `system_suggested_discount_pct`, `model_version`, `rule_override`, `fallback_used`, `requires_human_approval` | captured at review time, **never overwritten** |
| **Context (retraining)** | `context_features jsonb`, `model_metadata jsonb` | snapshot of `input_context` + `competitor_signals` + `decision_payload` + SHAP |
| **Human decision** | `review_action` (`accept`/`override`/`reject`), `final_decision`, `final_price_usd`, `final_discount_pct`, `review_note` | `final_decision` null only for reject-without-alternative |
| **Derived** | `is_override`, `agrees_with_system` | computed server-side |
| **Reviewer** | `reviewer_user_id`, `reviewer_email`, `reviewer_role`, `reviewed_via` | from the auth session |
| **Audit** | `revision`, `reviewed_at`, `created_at`, `updated_at` | revision bumps on every edit |

### `marketing.recommendation_review_history` (append-only)

Every create/edit writes a row: `revision`, `action` (`created`/`updated`), `before_state jsonb`,
`after_state jsonb`, `changed_by_email`, `change_reason`, `created_at`. Combined with the existing
`core.audit_logs` write, this gives complete change history — no review information is lost.

### Views

- **`marketing.v_recommendation_training_labels`** — the retraining dataset. One row per review:
  `context_features`, `system_recommendation`, `ground_truth_label`, `review_action`, `is_override`,
  `model_version`, `reviewer_email`, `reviewed_at`. `ground_truth_label` resolves to the human's
  `final_decision`; for an *accept* it is the system recommendation; for a *reject* without an
  alternative it is `NULL`.
- **`marketing.v_recommendation_review_analytics`** — per tenant × model_version × system decision:
  accept/override/reject counts, `acceptance_rate`, `override_rate`, `agreement_rate`.

---

## 3. Backend

### Repository — `eep/human_validation_db.py`

Mirrors `eep/retail_db.py` conventions (`_connect`, `_context`, `_audit`, JSON/number helpers),
fully tenant-isolated.

| Function | Purpose |
|---|---|
| `create_review(...)` | Upsert the current review for a SKU. Reads + freezes the system snapshot, computes `is_override`/`agrees_with_system`, writes history + audit. |
| `update_review(review_id, ...)` | Edit in place; bumps revision; system snapshot stays frozen. |
| `list_reviews / get_review / get_current_review_for_sku / get_review_history` | Reads. |
| `get_review_analytics(tenant)` | Acceptance/override/agreement + a weekly **trend**. |
| `get_review_analytics_cross_tenant()` | Admin: aggregate by `model_version`. |
| `export_training_labels(...)` | Pull ground-truth labels from the view for retraining. |

Pure helpers `resolve_final_decision`, `compute_agreement`, `validate_review_payload` are
unit-tested without a database.

### API endpoints — `eep/main.py`

| Method & path | Auth | Purpose |
|---|---|---|
| `POST /recommendations/{sku_id}/review` | shop | Submit accept/override/reject |
| `GET /recommendations/{sku_id}/review` | shop | Current review for a SKU |
| `GET /recommendations/reviews` | shop | List (filter by `action`, `model_version`) |
| `PUT /recommendations/reviews/{review_id}` | shop | Edit a review (audited) |
| `GET /recommendations/reviews/{review_id}/history` | shop | Change history |
| `GET /analytics/recommendation-reviews` | shop | Acceptance/override/agreement + trend |
| `GET /admin/recommendation-reviews/aggregate` | admin | Cross-tenant, by model version |
| `GET /admin/export/training-labels` | admin | JSONL export for retraining |

Validation (Pydantic + repository): `override` requires `final_decision`; `reject` requires a `note`.
On accept/override with a concrete decision the existing closed-loop **outcome snapshot** is still
scheduled (`_snapshot_in_background`), so sales-outcome tracking keeps working unchanged.

---

## 4. Frontend

- `frontend/src/lib/adapter.ts` — `submitRecommendationReview`, `fetchReviewForSku`,
  `fetchRecommendationReviews`, `updateRecommendationReview`, `fetchReviewAnalytics`.
- `frontend/src/components/recommendations/RecommendationDrawer.tsx` — the **Accept / Override /
  Snooze / Reject** actions now persist to the backend (in live/authenticated mode). An **override
  decision selector** (HOLD/MARKDOWN/PROMOTE/CLEAR) and a **reason note** were added; the markdown
  margin simulator feeds `final_price_usd`/`final_discount_pct`. Local state is still updated for
  instant UI; mock/offline mode is unchanged.
- `frontend/src/pages/Queue.tsx` — a compact analytics strip shows **acceptance %, override %,
  agreement %, reviews, rejected**.

---

## 5. Retraining usage

ML pipelines read the view directly — no application logic required:

```sql
SELECT context_features, ground_truth_label, model_version, reviewed_at
FROM   marketing.v_recommendation_training_labels
WHERE  ground_truth_label IS NOT NULL
  AND  reviewed_at >= now() - interval '90 days';
```

Or via the admin export endpoint (JSON Lines, one review per line):

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "https://retailradar.site/api/admin/export/training-labels?since=2026-01-01" \
  > training_labels.jsonl
```

Each line carries `context_features` (the exact model inputs at decision time) and
`ground_truth_label` (the human decision), so a training job can join them with zero reconstruction.

---

## 6. Analytics

`GET /analytics/recommendation-reviews` returns:

```json
{
  "total_reviews": 42, "accept_count": 30, "override_count": 9, "reject_count": 3,
  "acceptance_rate": 0.71, "override_rate": 0.21, "agreement_rate": 0.71,
  "by_decision": [{ "system_recommendation": "MARKDOWN", "acceptance_rate": 0.66, ... }],
  "trend": [{ "week": "2026-05-25T00:00:00+00:00", "total_reviews": 12, "acceptance_rate": 0.75 }]
}
```

`acceptance_rate` and `override_rate` measure how often humans follow vs. change the model;
`agreement_rate` is the human↔system match rate. The `by_decision` breakdown and the admin
`/admin/recommendation-reviews/aggregate` endpoint let you compare **performance by model version**.

---

## 7. Assumptions

1. **Action semantics:** accept = keep system; override = different decision (`final_decision`
   required); reject = decline (`note` required, no alternative). `ground_truth_label` = the human
   decision, resolving to the system recommendation for accepts and excluded for rejects-without-
   alternative.
2. **Reviewer = authenticated shop user** (auth context). `reviewed_via` defaults to `web`; the
   field exists so Telegram/API origins can be added later without a schema change.
3. **One current review per SKU**, edited in place with full revision history — preserving "the
   original recommendation is never overwritten" while keeping an auditable trail.
4. **Migration auto-applies** via the additive-schema path; no separate ops runbook.

---

## 8. Deployment notes

- No manual migration: `008_human_validation.sql` is applied automatically on first DB connect.
- No new services or containers; this is an additive change to the existing EEP + frontend.
- Backward compatible: existing `/decisions` and price-patch flows are untouched and still write
  `core.audit_logs`.

---

## 9. Verification

```bash
# Unit tests (pure logic + fake-DB write path)
pytest tests/unit/test_human_validation.py -v

# Schema (after starting EEP against Postgres)
psql "$DATABASE_URL" -c "\dt marketing.recommendation_review*"
psql "$DATABASE_URL" -c "\dv marketing.v_recommendation_*"
```

End-to-end: run a system-decision sync, open a SKU in the Queue drawer, submit **Accept** then
**Override** (with a note); confirm rows appear in `marketing.recommendation_reviews` and
`marketing.recommendation_review_history`, while `marketing.system_decision_latest.recommendation`
and `marketing.recommendations.recommendation` remain **unchanged**.
