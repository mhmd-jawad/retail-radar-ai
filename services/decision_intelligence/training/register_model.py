"""
Register the best training run model in MLflow Model Registry.

This script does not trust the local ``model.cbm`` as the source of truth.
Instead, it:
  1. reads ``meta.json`` written by ``train.py``
  2. finds the recorded best trial number
  3. finds the matching MLflow run (for example ``catboost_trial_017``)
  4. ensures that run has an MLflow-formatted model artifact
  5. registers the model version from that MLflow run artifact

Run from the repo root:
    py services/decision_intelligence/training/register_model.py
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

import mlflow
from catboost import CatBoostClassifier
from mlflow.tracking import MlflowClient


log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

ROOT = Path(__file__).resolve().parents[3]
META_PATH = ROOT / "services" / "decision_intelligence" / "models" / "catboost_decision" / "meta.json"
LOCAL_MLFLOW_MODEL_DIR = ROOT / "services" / "decision_intelligence" / "models" / "mlflow_export"


def _load_meta(meta_path: Path) -> dict:
    if not meta_path.exists():
        raise FileNotFoundError(f"Training metadata not found at: {meta_path}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _build_version_tags(meta: dict) -> dict[str, str]:
    # Copy useful training metadata onto the registered model version so the
    # registry page is informative without opening the original run.
    best_trial = meta.get("best_trial", {})
    params = best_trial.get("params", {})
    metrics = best_trial.get("metrics", {})

    tags = {
        "label_source": str(meta.get("label_source", "")),
        "training_dataset_path": str(meta.get("training_dataset_path", "")),
        "label_column": str(meta.get("label_column", "")),
        "num_features": str(len(meta.get("feature_cols", []))),
        "best_trial_number": str(best_trial.get("trial_number", "")),
    }

    for key, value in params.items():
        tags[f"param_{key}"] = str(value)

    for key, value in metrics.items():
        tags[f"metric_{key}"] = str(value)

    return {key: value for key, value in tags.items() if value != ""}


def _find_best_run(client: MlflowClient, experiment_name: str, trial_number: int):
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        raise ValueError(f"MLflow experiment not found: {experiment_name}")

    run_name = f"catboost_trial_{trial_number:03d}"
    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        filter_string=f"tags.mlflow.runName = '{run_name}'",
        max_results=1,
    )
    if not runs:
        raise ValueError(f"Could not find MLflow run named {run_name} in experiment {experiment_name}")
    return runs[0], run_name


def _artifact_uri_to_local_path(artifact_uri: str) -> Path:
    # Local MLflow artifact URIs look like:
    # mlflow-artifacts:/2/<run_id>/artifacts
    prefix = "mlflow-artifacts:/"
    if artifact_uri.startswith(prefix):
        relative = artifact_uri[len(prefix):].replace("/", "\\")
        return ROOT / "mlartifacts" / relative
    raise ValueError(f"Unsupported artifact URI format: {artifact_uri}")


def _find_trial_model_path(artifact_uri: str, trial_number: int) -> Path:
    # ``train.py`` logs raw CatBoost files under each run's model_files folder.
    return _artifact_uri_to_local_path(artifact_uri) / "model_files" / f"trial_{trial_number:03d}.cbm"


def _ensure_run_has_mlflow_model(
    run_id: str,
    artifact_uri: str,
    trial_number: int,
    tracking_uri: str,
    artifact_subpath: str,
    local_export_name: str | None = None,
) -> str:
    # If the winning run only has a raw .cbm file, convert it once into an
    # MLflow-formatted model artifact inside the same run.
    local_cbm = _find_trial_model_path(artifact_uri, trial_number)
    if not local_cbm.exists():
        raise FileNotFoundError(f"Expected trial model file not found at: {local_cbm}")

    export_dir = LOCAL_MLFLOW_MODEL_DIR / (local_export_name or f"trial_{trial_number:03d}_run_export")
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.parent.mkdir(parents=True, exist_ok=True)

    model = CatBoostClassifier()
    model.load_model(str(local_cbm))
    mlflow.catboost.save_model(cb_model=model, path=str(export_dir))

    mlflow.set_tracking_uri(tracking_uri)
    with mlflow.start_run(run_id=run_id):
        mlflow.log_artifacts(str(export_dir), artifact_path=artifact_subpath)

    return f"runs:/{run_id}/{artifact_subpath}"


def register_best_run_model(
    model_name: str,
    mlflow_tracking_uri: str,
    artifact_subpath: str,
    meta_path: Path = META_PATH,
    local_export_name: str | None = None,
) -> None:
    meta = _load_meta(meta_path)
    best_trial = meta.get("best_trial", {})
    trial_number = int(best_trial.get("trial_number"))
    experiment_name = str(meta.get("mlflow_experiment", "")).strip()
    if not experiment_name:
        raise ValueError("meta.json does not contain an mlflow_experiment value.")

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    client = MlflowClient(tracking_uri=mlflow_tracking_uri)

    # This is the important part: registration starts from the winning MLflow
    # run, not from the local best-model file.
    run, run_name = _find_best_run(client, experiment_name, trial_number)
    run_id = run.info.run_id
    source_uri = _ensure_run_has_mlflow_model(
        run_id=run_id,
        artifact_uri=run.info.artifact_uri,
        trial_number=trial_number,
        tracking_uri=mlflow_tracking_uri,
        artifact_subpath=artifact_subpath,
        local_export_name=local_export_name,
    )

    try:
        client.create_registered_model(model_name)
        log.info("Created registered model '%s'.", model_name)
    except Exception:
        log.info("Registered model '%s' already exists; creating a new version.", model_name)

    version = client.create_model_version(
        name=model_name,
        source=source_uri,
        run_id=run_id,
    )

    # Attach the best-trial params/metrics plus the originating run identity.
    tags = _build_version_tags(meta)
    tags["source_run_id"] = run_id
    tags["source_run_name"] = run_name
    for key, value in tags.items():
        client.set_model_version_tag(name=model_name, version=version.version, key=key, value=value)

    log.info("Registered model '%s' from MLflow run %s as version %s.", model_name, run_name, version.version)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register the best MLflow training run as a model version.")
    parser.add_argument(
        "--model-name",
        default="retail_radar_decision_model",
        help="Registered model name in MLflow.",
    )
    parser.add_argument(
        "--mlflow-tracking-uri",
        default="http://127.0.0.1:5000",
        help="MLflow tracking URI.",
    )
    parser.add_argument(
        "--artifact-subpath",
        default="registered_model_export",
        help="Artifact subpath to store the MLflow-formatted model inside the winning run.",
    )
    parser.add_argument(
        "--meta-path",
        type=Path,
        default=META_PATH,
        help="Path to the training meta.json to register.",
    )
    parser.add_argument(
        "--local-export-name",
        default=None,
        help="Optional folder name under services/decision_intelligence/models/mlflow_export for the exported model.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    register_best_run_model(
        model_name=args.model_name,
        mlflow_tracking_uri=args.mlflow_tracking_uri,
        artifact_subpath=args.artifact_subpath,
        meta_path=args.meta_path,
        local_export_name=args.local_export_name,
    )
