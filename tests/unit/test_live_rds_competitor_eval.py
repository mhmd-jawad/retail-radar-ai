from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from services.decision_intelligence.evaluation.live_rds_competitor_eval import (
    AILabel,
    LABELING_SYSTEM_PROMPT,
    LABEL_CANDIDATE_COLUMNS,
    LABEL_PROMPT_EXCLUDED_FIELDS,
    evaluate_live_rds_competitor_data,
    load_ai_labels,
)
from services.decision_intelligence.evaluation.live_rds_metrics import render_prometheus_metrics


def test_load_ai_labels_reads_explicit_expected_labels():
    labels_path = Path(".pytest-workspace/live_rds_labels_valid.csv")
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        labels_path.write_text(
            "sku_id,expected_label,ai_label_rationale\n"
            "SKU-1,promote,Healthy stock and attractive market position.\n",
            encoding="utf-8",
        )

        labels = load_ai_labels(labels_path)

        assert labels["SKU-1"] == AILabel(
            label="PROMOTE",
            rationale="Healthy stock and attractive market position.",
        )
    finally:
        labels_path.unlink(missing_ok=True)


def test_load_ai_labels_rejects_invalid_expected_label():
    labels_path = Path(".pytest-workspace/live_rds_labels_invalid.csv")
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        labels_path.write_text(
            "sku_id,expected_label,ai_label_rationale\nSKU-1,DISCOUNT,Not a supported action.\n",
            encoding="utf-8",
        )

        try:
            load_ai_labels(labels_path)
        except ValueError as exc:
            assert "Invalid expected_label" in str(exc)
        else:
            raise AssertionError("load_ai_labels should reject unsupported labels")
    finally:
        labels_path.unlink(missing_ok=True)


def test_live_eval_uses_exact_and_fallback_matching():
    products = [
        {
            "sku_id": "SKU-EXACT",
            "style_code": "ABC123",
            "brand": "Adidas",
            "product_name": "Adidas Ultraboost Runner Men",
            "system_category": "footwear",
            "gender": "men",
            "retail_price_usd": "100",
            "cost_price_usd": "50",
            "current_stock": "50",
            "initial_stock": "100",
        },
        {
            "sku_id": "SKU-FALLBACK",
            "style_code": "NOEXACT",
            "brand": "Adidas",
            "product_name": "Adidas Solar Glide Runner Trail Men",
            "system_category": "footwear",
            "gender": "men",
            "retail_price_usd": "100",
            "cost_price_usd": "50",
            "current_stock": "45",
            "initial_stock": "90",
        },
    ]
    competitors = pd.DataFrame(
        [
            _competitor(style_code="ABC123", product_name="Adidas Ultraboost Runner Men", competitor_price=90),
            _competitor(style_code="DIFF999", product_name="Adidas Solar Glide Runner Trail Men", competitor_price=95),
        ]
    )

    report = evaluate_live_rds_competitor_data(
        sample_size="all",
        output_path=None,
        candidates_path=None,
        product_rows=products,
        competitor_rows=competitors,
        model_predictor=lambda features: {
            "prediction": "HOLD",
            "confidence": 0.75,
            "probabilities": {"HOLD": 0.75},
        },
        system_predictor=lambda request: {
            "recommendation": "HOLD",
            "confidence": 0.8,
            "fallback_used": False,
            "rule_override": None,
        },
        ai_labels={
            "SKU-EXACT": AILabel("HOLD", "AI-reviewed exact-match hold case."),
            "SKU-FALLBACK": AILabel("PROMOTE", "AI-reviewed fallback-match promote case."),
        },
    )

    match_types = {case["sku_id"]: case["match"]["match_type"] for case in report["cases"]}
    assert match_types["SKU-EXACT"] == "exact_style"
    assert match_types["SKU-FALLBACK"] in {"same_model_family", "similar_product"}
    assert "macro_f1" in report["scoring"]["model_only"]
    assert "macro_f1" in report["scoring"]["system"]
    assert report["summary"]["evaluated_cases"] == 2
    assert report["summary"]["unlabeled_case_count"] == 0
    assert report["summary"]["expected_label_distribution"] == {"HOLD": 1, "PROMOTE": 1}


def test_label_candidates_use_business_only_prompt_payload():
    candidates_path = Path(".pytest-workspace/live_rds_label_candidates.csv")
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    products = [
        {
            "sku_id": "SKU-EXACT",
            "style_code": "ABC123",
            "brand": "Adidas",
            "product_name": "Adidas Ultraboost Runner Men",
            "system_category": "footwear",
            "gender": "men",
            "retail_price_usd": "100",
            "cost_price_usd": "50",
            "current_stock": "50",
            "initial_stock": "100",
        }
    ]
    competitors = pd.DataFrame(
        [_competitor(style_code="ABC123", product_name="Adidas Ultraboost Runner Men", competitor_price=90)]
    )

    try:
        evaluate_live_rds_competitor_data(
            sample_size="all",
            output_path=None,
            candidates_path=candidates_path,
            product_rows=products,
            competitor_rows=competitors,
            model_predictor=lambda features: {
                "prediction": "MARKDOWN",
                "confidence": 0.77,
                "probabilities": {"MARKDOWN": 0.77},
            },
            system_predictor=lambda request: {
                "recommendation": "PROMOTE",
                "confidence": 0.81,
                "fallback_used": False,
                "rule_override": None,
            },
            ai_labels={"SKU-EXACT": AILabel("HOLD", "Known expected label that must not leak.")},
        )

        with candidates_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        assert reader.fieldnames == LABEL_CANDIDATE_COLUMNS
        assert set(reader.fieldnames or []).isdisjoint(LABEL_PROMPT_EXCLUDED_FIELDS)
        assert rows[0]["sku_id"] == "SKU-EXACT"
        assert rows[0]["match_type"] == "exact_style"
        assert "model prediction" in LABELING_SYSTEM_PROMPT
        assert "system prediction" in LABELING_SYSTEM_PROMPT
    finally:
        candidates_path.unlink(missing_ok=True)


def test_prometheus_renderer_includes_f1_and_matching_metrics():
    text = render_prometheus_metrics(
        {
            "summary": {
                "evaluated_cases": 2,
                "requested_sample_size_numeric": 2,
                "valid_request_count": 2,
                "unlabeled_case_count": 0,
                "skipped_product_count": 0,
                "expected_label_distribution": {"HOLD": 1, "MARKDOWN": 1},
            },
            "freshness": {"median_freshness_hours": 12},
            "matching": {
                "no_match_rate": 0.0,
                "match_type_distribution": {"exact_style": 1, "same_model_family": 1},
                "coverage_ratio": {"exact": 0.5, "fallback": 0.5, "no_match": 0.0},
            },
            "scoring": {
                "model_only": {
                    "accuracy": 0.5,
                    "macro_f1": 0.5,
                    "weighted_f1": 0.5,
                    "mean_confidence": 0.8,
                    "median_confidence": 0.8,
                    "predicted_distribution": {"HOLD": 2},
                    "per_class_metrics": {"HOLD": {"precision": 0.5, "recall": 1, "f1": 0.6667, "support": 1}},
                }
            },
        }
    )

    assert 'live_rds_eval_macro_f1{mode="model_only"} 0.5' in text
    assert 'live_rds_eval_f1{label="HOLD",mode="model_only"} 0.6667' in text
    assert 'live_rds_eval_match_total{match_type="same_model_family"} 1.0' in text
    assert 'live_rds_eval_expected_label_total{label="MARKDOWN"} 1.0' in text


def _competitor(style_code: str, product_name: str, competitor_price: float):
    return {
        "brand_name": "Adidas",
        "style_code": style_code,
        "competitor_name": "mikesport",
        "product_name": product_name,
        "category": "footwear",
        "gender_target": "men",
        "competitor_price": competitor_price,
        "competitor_sale_price": "",
        "discount_pct": "",
        "is_on_sale": "false",
        "availability": "in_stock",
        "currency": "USD",
        "source_url": f"https://example.test/{style_code}",
        "scraped_at": "2026-05-27T10:00:00+00:00",
        "data_valid": "true",
    }
