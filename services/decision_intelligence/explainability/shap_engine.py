"""
Real SHAP explainability for the IE2 CatBoost multi-class model.

This module uses CatBoost's native SHAP implementation so explanations match
the actual trained classifier, including categorical feature handling.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import catboost as cb

from .templates import explain_feature

if TYPE_CHECKING:
    import pandas as pd


ROOT = Path(__file__).parent.parent
MODEL_PATH = ROOT / "models" / "catboost_decision" / "model.cbm"

LABEL_MAP = {0: "HOLD", 1: "MARKDOWN", 2: "PROMOTE", 3: "CLEAR"}


class SHAPEngine:
    """Thin wrapper around CatBoost's native SHAP output."""

    def __init__(self, model: Any, cat_features: list[str] | None = None) -> None:
        self._model = model
        self._cat_features = list(cat_features or [])

    @classmethod
    def load(
        cls,
        model_path: Path = MODEL_PATH,
        cat_features: list[str] | None = None,
    ) -> "SHAPEngine":
        """Load a local CatBoost model file for offline SHAP use."""
        if not model_path.exists():
            raise FileNotFoundError(
                f"Model not found: {model_path}\n"
                "Train first: python -m services.decision_intelligence.training.train"
            )
        model = cb.CatBoostClassifier()
        model.load_model(str(model_path))
        return cls(model, cat_features=cat_features)

    def explain(self, X: "pd.DataFrame", predicted_class_idx: int) -> list[dict[str, Any]]:
        """
        Return the top 5 real SHAP contributions for a single row and class.

        The response shape matches the SHAPFeature schema used by the API.
        """
        if X.empty:
            return []

        pool = cb.Pool(
            X,
            cat_features=self._cat_features,
            feature_names=X.columns.tolist(),
        )
        shap_tensor = self._model.get_feature_importance(type="ShapValues", data=pool)
        shap_for_class = shap_tensor[0, predicted_class_idx, :-1]

        feature_names = X.columns.tolist()
        feature_values = X.iloc[0].tolist()
        pairs = sorted(
            zip(feature_names, shap_for_class, feature_values),
            key=lambda item: abs(float(item[1])),
            reverse=True,
        )

        top5: list[dict[str, Any]] = []
        for feature_name, shap_value, feature_value in pairs[:5]:
            shap_value = float(shap_value)
            direction = "increases_probability" if shap_value >= 0 else "decreases_probability"
            if isinstance(feature_value, bool):
                normalized_value: float | str = int(feature_value)
            elif isinstance(feature_value, (int, float)):
                normalized_value = round(float(feature_value), 4)
            else:
                normalized_value = str(feature_value)

            top5.append(
                {
                    "feature_name": feature_name,
                    "feature_value": normalized_value,
                    "shap_value": round(shap_value, 4),
                    "direction": direction,
                    "explanation": explain_feature(
                        feature_name,
                        normalized_value,
                        shap_value,
                        LABEL_MAP.get(predicted_class_idx, "HOLD"),
                    ),
                }
            )
        return top5
