"""Prometheus rendering for the latest live RDS evaluation report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_PATH = ROOT / "data" / "reports" / "live_rds_competitor_eval.json"


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

    return "\n".join(lines) + "\n"


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
