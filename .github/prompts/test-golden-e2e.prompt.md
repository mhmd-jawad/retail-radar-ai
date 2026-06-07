---
description: "Expand the existing golden scenario integration tests to run through the full _recommend_single() function (model + rules), not just the rules engine in isolation"
name: "Golden Scenarios E2E Integration Tests"
agent: "agent"
---

Expand the existing `tests/integration/golden/test_golden_scenarios.py` to add a second test class that threads each golden scenario through `_recommend_single()` (the full IE2 pipeline: model inference + rules override), not just `run_rules()` directly.

## Context files to read first

- [tests/integration/golden/test_golden_scenarios.py](../../../tests/integration/golden/test_golden_scenarios.py) — existing 6 scenarios and their feature dictionaries
- [services/decision_intelligence/main.py](../../../services/decision_intelligence/main.py) — `_recommend_single()`, `RecommendationRequest` usage
- [services/decision_intelligence/schemas.py](../../../services/decision_intelligence/schemas.py) — `RecommendationRequest`, `RecommendationResult`
- [services/decision_intelligence/models/catboost_decision/meta.json](../../../services/decision_intelligence/models/catboost_decision/meta.json) — full feature list required by the model

## What to add (do NOT delete existing tests)

Add a new class `TestGoldenScenariosE2E` inside the existing file with 6 async tests — one per scenario.

### Scenario mapping

| Test | Features source | Expected `recommendation` | Assertion logic |
|---|---|---|---|
| `test_s1_healthy_sku_hold_e2e` | S1 features from existing test | `HOLD` | exact match |
| `test_s2_dead_stock_clear_e2e` | S2 features | `CLEAR` | exact match |
| `test_s3_low_stock_hold_e2e` | S3 features | `HOLD` | exact match; also assert `MARKDOWN` not in `result.blocked_actions` or rules blocked it |
| `test_s4_margin_floor_blocks_markdown_e2e` | S4 features | not `MARKDOWN` | assert recommendation != MARKDOWN |
| `test_s5_recent_discount_blocks_markdown_e2e` | S5 features | not `MARKDOWN` | assert recommendation != MARKDOWN |
| `test_s6_event_nudge_soft_override_e2e` | S6 features | `PROMOTE` | exact match; assert no hard override (confidence >= 0.5) |

### For each test:
1. Build a `RecommendationRequest` from the existing scenario feature dict — pad any missing fields from `meta.json`'s `feature_cols` with sensible defaults (e.g. 0.0 for floats, 1 for ints, `"unknown"` for categoricals)
2. Call `result = await _recommend_single(req)` directly
3. Assert recommendation matches expectation
4. Assert `result.shap_top5` is a list (may be empty if rules short-circuit)
5. Assert `result.processing_time_ms >= 0`

### Module-level skip guard
```python
import pytest
from pathlib import Path
from services.decision_intelligence.main import LOCAL_PINNED_MODEL_EXPORT_DIR

pytestmark = pytest.mark.skipif(
    not (Path(LOCAL_PINNED_MODEL_EXPORT_DIR) / "model.cbm").exists(),
    reason="CatBoost model not present — skipping E2E golden tests"
)
```
Apply this only to the new `TestGoldenScenariosE2E` class (not the existing `TestGoldenScenarios` class).

## Constraints
- **Do not remove or modify** any existing test in `TestGoldenScenarios`
- The existing tests call `run_rules(features)` — keep them as-is; they test the rules engine in isolation which is still valuable
- No mocking — `TestGoldenScenariosE2E` uses the real model and real rules engine
- No real database calls are needed (features are passed directly)
- Use `asyncio_mode = auto` (no `@pytest.mark.asyncio` decorator needed)
