-- Migration 003: Add explainability columns to marketing.recommendations
-- Stores SHAP feature breakdown and rule override detail so the Telegram assistant
-- can retrieve rich reasoning without calling IE2 a second time.

ALTER TABLE marketing.recommendations
    ADD COLUMN IF NOT EXISTS shap_features_json  JSONB    DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS rule_override_json  JSONB    DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS fallback_used       BOOLEAN  DEFAULT FALSE NOT NULL,
    ADD COLUMN IF NOT EXISTS model_version       TEXT     DEFAULT 'unknown';

COMMENT ON COLUMN marketing.recommendations.shap_features_json IS
    'Top-5 SHAP features from IE2: [{feature_name, feature_value, shap_value, direction, explanation}]';
COMMENT ON COLUMN marketing.recommendations.rule_override_json IS
    'Hard rule that fired, if any: {rule_id, override_strength, reason, blocked_actions}';
COMMENT ON COLUMN marketing.recommendations.fallback_used IS
    'TRUE when model confidence < 0.45 and recommendation defaulted to HOLD';
COMMENT ON COLUMN marketing.recommendations.model_version IS
    'IE2 model version that generated this recommendation, e.g. catboost_v6';
