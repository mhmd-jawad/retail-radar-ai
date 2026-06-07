---
description: "Generate integration tests for the IE2 Decision Intelligence model — loads the real CatBoost model from disk and runs _recommend_single() end-to-end"
name: "IE2 Model Integration Tests"
agent: "agent"
---

Generate a new test file at `tests/integration/test_ie2_model.py` for the IE2 Decision Intelligence service.

## Context files to read first

- [services/decision_intelligence/main.py](../../services/decision_intelligence/main.py) — `_recommend_single()`, `_load_model()`, `LOCAL_PINNED_MODEL_EXPORT_DIR`
- [services/decision_intelligence/schemas.py](../../services/decision_intelligence/schemas.py) — `RecommendationRequest`, `RecommendationResult`
- [services/decision_intelligence/rules/](../../services/decision_intelligence/rules/) — rules engine used inside `_recommend_single()`
- [services/decision_intelligence/models/catboost_decision/meta.json](../../services/decision_intelligence/models/catboost_decision/meta.json) — feature list, label map
- [tests/integration/golden/test_golden_scenarios.py](../../tests/integration/golden/test_golden_scenarios.py) — existing test style to follow
- [pytest.ini](../../pytest.ini) — asyncio_mode = auto

## Requirements

### Test class: `TestIE2ModelLoads`
- `test_model_file_exists` — assert `LOCAL_PINNED_MODEL_EXPORT_DIR / "model.cbm"` exists
- `test_model_loads_without_error` — call `_load_model()`, assert returns a non-None CatBoostClassifier

### Test class: `TestRecommendSingleAllDecisions`
Create one async test per decision type, each using a `RecommendationRequest` with feature values crafted to force a deterministic output:

| Test | Expected `recommendation` | Key features to set |
|---|---|---|
| `test_hold_decision` | `HOLD` | `days_of_supply=10`, `total_qty=5` |
| `test_markdown_decision` | `MARKDOWN` | `days_of_supply=95`, `current_margin_pct=30`, `price_gap_pct=0.08` |
| `test_promote_decision` | `PROMOTE` | `days_of_supply=45`, `seasonality_score=1.3`, `current_margin_pct=40` |
| `test_clear_decision` | `CLEAR` | `days_of_supply=130`, `season_sell_through_pct=0.10` |

Each test must:
1. Call `await _recommend_single(req)` directly (no HTTP)
2. Assert `result.recommendation == "<EXPECTED>"`
3. Assert `result.confidence` is between 0.0 and 1.0
4. Assert `result.shap_top5` is a non-empty list
5. Assert `result.processing_time_ms > 0`

### Test class: `TestRecommendSingleOutputShape`
- `test_result_is_recommendation_result` — assert the return type is `RecommendationResult`
- `test_explanation_is_non_empty_string` — assert `result.explanation` is a non-empty string
- `test_shap_top5_has_valid_fields` — for each entry in `result.shap_top5`, assert `feature_name`, `shap_value`, `direction` are present

## Constraints
- Use `pytest.mark.skipif` with `not Path(LOCAL_PINNED_MODEL_EXPORT_DIR / "model.cbm").exists()` to skip model tests when the model is absent (CI without LFS)
- Use `@pytest_asyncio.fixture` for any async fixtures (not `@pytest.fixture`)
- No mocking — these are real model calls
- Use `asyncio_mode = auto` (already in pytest.ini, no `@pytest.mark.asyncio` needed)
- Populate all required fields from `meta.json`'s `feature_cols` list with sensible numeric defaults; categorical fields (`category`, `brand`, `market_position`, `brand_tier`) must be set to valid strings
