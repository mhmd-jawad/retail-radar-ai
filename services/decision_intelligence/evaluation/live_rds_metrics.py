"""Prometheus rendering for the latest live RDS evaluation report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_PATH = ROOT / "data" / "reports" / "live_rds_competitor_eval.json"
DEFAULT_RDS_DATASET_REPORT_PATH = ROOT / "data" / "reports" / "rds_expanded_training_dataset_summary.json"
DEFAULT_ACTIVE_RDS_DATASET_REPORT_PATH = (
    ROOT / "data" / "reports" / "rds_leak_safe_training_dataset_summary.json"
)
DEFAULT_CANDIDATE_META_PATH = (
    ROOT / "services" / "decision_intelligence" / "models" / "catboost_decision" / "meta.json"
)


def load_latest_report(path: Path | None = None) -> dict[str, Any]:
    report_path = path or DEFAULT_REPORT_PATH
    if not report_path.exists():
        return {}
    return json.loads(report_path.read_text(encoding="utf-8"))


def render_prometheus_metrics(report: dict[str, Any] | None = None) -> str:
    payload = report or load_latest_report()
    lines = [
        "# HELP live_rds_eval_report_present Whether a live RDS evaluation report exists.",
        "# TYPE live_rds_eval_report_present gauge",
    ]
    if not payload:
        lines.append("live_rds_eval_report_present 0")
        return "\n".join(lines) + "\n"

    summary = payload.get("summary", {})
    scoring = payload.get("scoring", {})
    matching = payload.get("matching", {})
    freshness = payload.get("freshness", {})

    lines.append("live_rds_eval_report_present 1")
    _gauge(lines, "live_rds_eval_sample_size", summary.get("evaluated_cases", 0))
    _gauge(lines, "live_rds_eval_requested_sample_size", summary.get("requested_sample_size_numeric", 0))
    _gauge(lines, "live_rds_eval_valid_request_count", summary.get("valid_request_count", 0))
    _gauge(lines, "live_rds_eval_unlabeled_case_count", summary.get("unlabeled_case_count", 0))
    _gauge(lines, "live_rds_eval_skipped_product_count", summary.get("skipped_product_count", 0))
    _gauge(lines, "live_rds_eval_median_freshness_hours", freshness.get("median_freshness_hours", 0))
    _gauge(lines, "live_rds_eval_fallback_rate", matching.get("no_match_rate", 0))

    for mode, metrics in scoring.items():
        labels = {"mode": mode}
        _gauge(lines, "live_rds_eval_accuracy", metrics.get("accuracy", 0), labels)
        _gauge(lines, "live_rds_eval_macro_f1", metrics.get("macro_f1", 0), labels)
        _gauge(lines, "live_rds_eval_macro_f1_all_classes", metrics.get("macro_f1_all_classes", 0), labels)
        _gauge(lines, "live_rds_eval_weighted_f1", metrics.get("weighted_f1", 0), labels)
        _gauge(lines, "live_rds_eval_mean_confidence", metrics.get("mean_confidence", 0), labels)
        _gauge(lines, "live_rds_eval_median_confidence", metrics.get("median_confidence", 0), labels)
        for label, count in metrics.get("predicted_distribution", {}).items():
            _gauge(lines, "live_rds_eval_prediction_total", count, {"mode": mode, "label": label})
        for label, class_metrics in metrics.get("per_class_metrics", {}).items():
            metric_labels = {"mode": mode, "label": label}
            _gauge(lines, "live_rds_eval_precision", class_metrics.get("precision", 0), metric_labels)
            _gauge(lines, "live_rds_eval_recall", class_metrics.get("recall", 0), metric_labels)
            _gauge(lines, "live_rds_eval_f1", class_metrics.get("f1", 0), metric_labels)
            _gauge(lines, "live_rds_eval_support", class_metrics.get("support", 0), metric_labels)

    expected_labels = summary.get("expected_label_distribution", {})
    for label, count in expected_labels.items():
        _gauge(lines, "live_rds_eval_expected_label_total", count, {"label": label})
    for match_type, count in matching.get("match_type_distribution", {}).items():
        _gauge(lines, "live_rds_eval_match_total", count, {"match_type": match_type})
    for group, ratio in matching.get("coverage_ratio", {}).items():
        _gauge(lines, "live_rds_eval_match_coverage_ratio", ratio, {"match_group": group})

    _render_rds_candidate_dataset_metrics(lines)
    _render_rds_candidate_training_metrics(lines)

    return "\n".join(lines) + "\n"


def _render_rds_candidate_dataset_metrics(
    lines: list[str],
    path: Path = DEFAULT_ACTIVE_RDS_DATASET_REPORT_PATH,
) -> None:
    lines.extend(
        [
            "# HELP rds_candidate_dataset_present Whether the RDS expanded candidate dataset summary exists.",
            "# TYPE rds_candidate_dataset_present gauge",
        ]
    )
    if not path.exists():
        lines.append("rds_candidate_dataset_present 0")
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    lines.append("rds_candidate_dataset_present 1")
    row_counts = payload.get("row_counts", {})
    dataset_rows = row_counts.get("augmented_final", row_counts.get("final_candidate_rows", 0))
    training_rows = row_counts.get("train_real", row_counts.get("training_rows", 0))
    _gauge(lines, "rds_candidate_dataset_rows", dataset_rows)
    _gauge(lines, "rds_candidate_training_rows", training_rows)
    _gauge(lines, "rds_candidate_test_rows", row_counts.get("test_real", 0))
    _gauge(lines, "rds_candidate_synthetic_rows", row_counts.get("synthetic_rows", 0))
    _gauge(lines, "rds_candidate_review_candidate_rows", row_counts.get("review_candidate_rows", 0))
    _gauge(lines, "rds_candidate_larger_than_current_baseline", 1 if dataset_rows > 5968 else 0)
    audit = payload.get("audit", {})
    _gauge(lines, "rds_candidate_snapshot_rows", audit.get("snapshot_rows", 0))
    _gauge(lines, "rds_candidate_scrape_weeks", audit.get("scrape_weeks", 0))
    _gauge(lines, "rds_candidate_exact_style_coverage_ratio", audit.get("exact_style_coverage_ratio", 0))
    label_distribution = payload.get("label_distribution", {})
    if isinstance(label_distribution.get("augmented_final"), dict):
        label_distribution = label_distribution.get("augmented_final", {})
    for label, count in label_distribution.items():
        _gauge(lines, "rds_candidate_label_total", count, {"label": label})
    for match_type, count in payload.get("match_type_distribution", {}).items():
        _gauge(lines, "rds_candidate_match_total", count, {"match_type": match_type})


def _render_rds_candidate_training_metrics(lines: list[str], path: Path = DEFAULT_CANDIDATE_META_PATH) -> None:
    lines.extend(
        [
            "# HELP rds_candidate_model_present Whether the RDS candidate model metadata exists.",
            "# TYPE rds_candidate_model_present gauge",
        ]
    )
    if not path.exists():
        lines.append("rds_candidate_model_present 0")
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    lines.append("rds_candidate_model_present 1")
    _gauge(lines, "rds_candidate_model_train_examples", payload.get("train_examples", 0))
    _gauge(lines, "rds_candidate_model_val_examples", payload.get("val_examples", 0))
    _gauge(lines, "rds_candidate_model_test_examples", payload.get("test_examples", 0))
    _gauge(lines, "rds_candidate_model_stress_test_examples", payload.get("stress_test_examples", 0))
    _gauge(lines, "rds_candidate_model_num_trials", payload.get("num_trials", 0))
    metrics = payload.get("best_trial", {}).get("metrics", {})
    for metric_name, value in metrics.items():
        if metric_name.startswith(
            (
                "val_",
                "test_real_",
                "clear_stress_",
                "precision_",
                "recall_",
                "f1_",
                "support_",
            )
        ) or metric_name == "best_iteration":
            _gauge(lines, "rds_candidate_model_metric", value, {"metric": metric_name})


def _gauge(lines: list[str], name: str, value: Any, labels: dict[str, Any] | None = None) -> None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    suffix = _labels(labels or {})
    lines.append(f"{name}{suffix} {numeric}")


def _labels(labels: dict[str, Any]) -> str:
    if not labels:
        return ""
    rendered = ",".join(f'{key}="{_escape(value)}"' for key, value in sorted(labels.items()))
    return "{" + rendered + "}"


def _escape(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
