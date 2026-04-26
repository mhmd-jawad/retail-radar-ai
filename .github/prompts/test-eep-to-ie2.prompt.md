---
description: "Generate integration tests for the EEP → IE2 pipeline using FastAPI TestClient — tests /recommend/{sku_id} and /recommend/batch without a live server"
name: "EEP ↔ IE2 Pipeline Integration Tests"
agent: "agent"
---

Generate a new test file at `tests/integration/test_eep_pipeline.py` for the EEP service's integration with IE2.

## Context files to read first

- [eep/main.py](../../eep/main.py) — all route handlers, especially `recommend_for_frontend`, `/recommend/batch`, `/recommend/full`
- [eep/retail_db.py](../../eep/retail_db.py) — `list_inventory_items()`, `get_product_details()`
- [services/decision_intelligence/main.py](../../services/decision_intelligence/main.py) — `_recommend_single()` (imported directly into EEP)
- [services/decision_intelligence/schemas.py](../../services/decision_intelligence/schemas.py) — `RecommendationRequest`, `RecommendationResult`
- [pytest.ini](../../pytest.ini)

## Requirements

### Fixtures (module-scoped)
- `app_client` — creates a `TestClient(app)` from `eep.main`; patches `eep.main._recommend_single` with an `AsyncMock` that returns a valid `RecommendationResult` (recommendation=`HOLD`, confidence=0.85, shap_top5=[], explanation="test", processing_time_ms=10, model_version="test", requires_human_approval=False)
- `db_mock` — patches `eep.retail_db.list_inventory_items` and `eep.retail_db.get_product_details` to return fixture data (one SKU: `SKU-TEST-001`)

### Test class: `TestSingleRecommend`
- `test_recommend_returns_200` — `GET /recommend/SKU-TEST-001` returns HTTP 200
- `test_recommend_response_schema` — response JSON has keys: `sku_id`, `recommendation`, `confidence`, `explanation`
- `test_recommend_unknown_sku_returns_404` — `GET /recommend/UNKNOWN-SKU-999` returns 404
- `test_recommend_calls_ie2_once` — assert `_recommend_single` was called exactly once with the correct `sku_id`

### Test class: `TestBatchRecommend`
- `test_batch_returns_200` — `POST /recommend/batch` with body `{"sku_ids": ["SKU-TEST-001", "SKU-TEST-002"]}` returns 200
- `test_batch_response_is_list` — response JSON is a list of length 2
- `test_batch_calls_are_parallel` — assert `_recommend_single` was called twice (gather, not sequential)
- `test_batch_empty_list_returns_empty` — POST with `{"sku_ids": []}` returns 200 with empty list `[]`

### Test class: `TestHealthEndpoint`
- `test_health_returns_200` — `GET /health` returns 200
- `test_health_has_status_ok` — response JSON contains `"status": "ok"`

## Constraints
- Use `httpx.AsyncClient(app=app, base_url="http://test")` for async route tests, or `starlette.testclient.TestClient` for sync — prefer `TestClient` (simpler)
- Mock ALL database calls — no real PostgreSQL connection
- Mock `_recommend_single` — no real model inference
- Use `unittest.mock.patch` and `AsyncMock` from `unittest.mock`
- No `@pytest.mark.asyncio` needed (`asyncio_mode = auto` in pytest.ini)
- Import the FastAPI `app` instance from `eep.main`
