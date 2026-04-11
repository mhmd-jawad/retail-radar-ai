"""
Rules-engine baseline labeler for IE2 training.

Reads features.csv, applies hard thresholds to generate training labels,
and writes labels.csv. This is the v1 label source until real merchant
outcome data is available.

Baseline logic (priority order):
  1. CLEAR  — DOS > 120 AND sell_through < 0.15
  2. HOLD   — qty < 15 OR DOS < 14
  3. MARKDOWN — DOS > 90 AND margin > 25 AND price_gap > 0.05
  4. PROMOTE  — DOS 20-90 AND seasonality >= 1.10 AND margin >= 35
  5. HOLD   — default

Usage:
    python -m services.decision_intelligence.training.baseline
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

ROOT = Path(__file__).parent.parent
FEATURES_PATH = ROOT / "data" / "features" / "features.csv"
LABELS_PATH   = ROOT / "data" / "features" / "labels.csv"


def _assign_label(row: pd.Series) -> str:
    dos    = float(row.get("days_of_supply", 9999))
    margin = float(row.get("current_margin_pct", 0))
    qty    = int(row.get("total_qty", 0))
    gap    = float(row.get("price_gap_pct", 0))
    sell   = float(row.get("season_sell_through_pct", 0))
    season = float(row.get("seasonality_score", 1.0))

    if dos > 120 and sell < 0.15:
        return "CLEAR"
    if qty < 15 or dos < 14:
        return "HOLD"
    if dos > 90 and margin > 25 and gap > 0.05:
        return "MARKDOWN"
    if 20 <= dos <= 90 and season >= 1.10 and margin >= 35:
        return "PROMOTE"
    return "HOLD"


def generate_labels(
    features_path: Path = FEATURES_PATH,
    labels_path: Path = LABELS_PATH,
) -> pd.DataFrame:
    if not features_path.exists():
        raise FileNotFoundError(
            f"Features not found: {features_path}\n"
            "Run: python -m services.decision_intelligence.features.engineer"
        )

    df = pd.read_csv(features_path)
    df["rules_label"] = df.apply(_assign_label, axis=1)

    labels_path.parent.mkdir(parents=True, exist_ok=True)
    df[["sku_id", "rules_label"]].to_csv(labels_path, index=False)

    dist = df["rules_label"].value_counts().to_dict()
    log.info("Label distribution: %s", dist)
    log.info("Labels saved → %s", labels_path)
    return df


if __name__ == "__main__":
    generate_labels()
