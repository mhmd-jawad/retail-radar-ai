---
description: "Generate end-to-end integration tests for the full PROMOTE pipeline: EEP → IE2 → IE3 campaign generation, with IE3's LLM and image calls mocked"
name: "Full PROMOTE Pipeline Integration Tests"
agent: "agent"
---

Generate a new test file at `tests/integration/test_promote_pipeline.py` that exercises the full PROMOTE decision flow from EEP through IE2 to IE3.

## Context files to read first

- [eep/main.py](../../eep/main.py) — `/recommend/full` route; how it calls IE2 then posts PROMOTE results to IE3
- [services/decision_intelligence/main.py](../../services/decision_intelligence/main.py) — `_recommend_single()`
- [services/decision_intelligence/schemas.py](../../services/decision_intelligence/schemas.py) — `RecommendationResult`
- [services/campaign_creative/main.py](../../services/campaign_creative/main.py) — `POST /campaign/generate`, `CampaignGenerateRequest`, `CampaignCreativeResponse`
- [tests/unit/test_campaign_creative.py](../../tests/unit/test_campaign_creative.py) — existing IE3 mock patterns to reuse

## Pipeline under test

```
EEP /recommend/full
    ↓
_recommend_single(sku_id)  →  RecommendationResult(recommendation="PROMOTE")
    ↓
POST http://localhost:8003/campaign/generate
    ↓ (mocked)
CampaignCreativeResponse
    ↓
EEP returns unified JSON response
```

## Requirements

### Fixtures
- `promote_result` — a `RecommendationResult` with `recommendation="PROMOTE"`, `confidence=0.91`, `suggested_discount_pct=15.0`, `requires_human_approval=True`, and 2 entries in `shap_top5`
- `campaign_response` — a `CampaignCreativeResponse` fixture with `headline`, `body_copy`, `cta`, `image_url` populated
- `full_pipeline_client` — `TestClient(eep_app)` with these patches:
  1. `eep.main._recommend_single` → `AsyncMock` returning `promote_result`
  2. `eep.retail_db.get_product_details` → returns 1 test product
  3. `httpx.AsyncClient.post` (IE3 call) → returns a mock response with status 200 and `campaign_response` JSON

### Test class: `TestFullPromotePipeline`
- `test_promote_triggers_campaign_generation` — call EEP `/recommend/full?sku_id=SKU-TEST-001`; assert `httpx.AsyncClient.post` was called once with URL containing `/campaign/generate`
- `test_full_response_contains_recommendation` — response JSON contains `recommendation.recommendation == "PROMOTE"`
- `test_full_response_contains_campaign` — response JSON contains a `campaign` key with `headline` and `cta`
- `test_non_promote_skips_campaign` — repeat with `_recommend_single` returning `recommendation="HOLD"`; assert `httpx.AsyncClient.post` was NOT called
- `test_requires_human_approval_propagated` — assert response JSON has `requires_human_approval: true` when `promote_result.requires_human_approval` is True

### Test class: `TestPromotePipelineEdgeCases`
- `test_ie3_timeout_returns_partial_response` — patch `httpx.AsyncClient.post` to raise `httpx.TimeoutException`; assert EEP returns HTTP 200 with `campaign: null` and `campaign_error` key (graceful degradation)
- `test_ie3_error_does_not_crash_eep` — patch `httpx.AsyncClient.post` to return status 500; assert EEP returns HTTP 200 with `campaign: null`

## Constraints
- Never make real HTTP calls to port 8003 — mock `httpx.AsyncClient.post`
- Never call the real CatBoost model — mock `_recommend_single`
- No real PostgreSQL — mock all `retail_db` calls
- Use `starlette.testclient.TestClient` for the EEP app
- If the EEP `/recommend/full` route does not currently implement graceful IE3 degradation, note it as a TODO comment in the test file and mark those tests with `pytest.mark.xfail(reason="EEP graceful IE3 degradation not yet implemented")`
