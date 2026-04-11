"""
SHAP explainability engine for IE2 Decision Intelligence.

STATUS: v1 stub — real SHAP values require a trained CatBoost model.
        v1 returns rule-derived explanations from _build_rule_explanations()
        in main.py. This module wires in TreeSHAP when the model is trained.

v2 usage (once model is ready):
    engine = SHAPEngine.load()
    shap_top5 = engine.explain(features_df, predicted_class_idx)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
MODEL_PATH = ROOT / "models" / "catboost_decision" / "model.cbm"

LABEL_MAP = {0: "HOLD", 1: "MARKDOWN", 2: "PROMOTE", 3: "CLEAR"}


class SHAPEngine:
    """TreeSHAP wrapper for CatBoost multi-class model."""

    def __init__(self, model) -> None:
        self._model = model
        self._explainer = None  # lazy init

    @classmethod
    def load(cls, model_path: Path = MODEL_PATH) -> "SHAPEngine":
        """Load a trained CatBoost model and prepare for SHAP inference."""
        try:
            import catboost as cb  # type: ignore
        except ImportError as e:
            raise SystemExit(f"Missing catboost: {e}") from e

        if not model_path.exists():
            raise FileNotFoundError(
                f"Model not found: {model_path}\n"
                "Train first: python -m services.decision_intelligence.training.train"
            )
        model = cb.CatBoostClassifier()
        model.load_model(str(model_path))
        return cls(model)

    def explain(self, X: "pd.DataFrame", predicted_class_idx: int) -> list[dict]:
        """
        Compute TreeSHAP values for one row X and return top 5 features.

        Returns list of dicts compatible with SHAPFeature schema:
            {feature_name, feature_value, shap_value, direction, explanation}
        """
        try:
            import shap  # type: ignore
        except ImportError as e:
            raise SystemExit(f"Missing shap: {e}") from e

        if self._explainer is None:
            self._explainer = shap.TreeExplainer(self._model)

        shap_matrix = self._explainer.shap_values(X)
        # shap_values returns shape (n_samples, n_features, n_classes) for CatBoost
        shap_for_class = shap_matrix[0, :, predicted_class_idx]

        feature_names = X.columns.tolist()
        pairs = sorted(
            zip(feature_names, shap_for_class, X.values[0]),
            key=lambda x: abs(x[1]),
            reverse=True,
        )

        from .templates import explain_feature
        top5 = []
        for fname, sval, fval in pairs[:5]:
            direction = "increases_probability" if sval > 0 else "decreases_probability"
            explanation = explain_feature(
                fname, float(fval), float(sval),
                LABEL_MAP.get(predicted_class_idx, "HOLD")
            )
            top5.append({
                "feature_name":  fname,
                "feature_value": round(float(fval), 4),
                "shap_value":    round(float(sval), 4),
                "direction":     direction,
                "explanation":   explanation,
            })
        return top5
