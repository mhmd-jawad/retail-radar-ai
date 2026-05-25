from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eep.apify_ingest import DEFAULT_SCHEMA_PATH
from sync_to_postgres import _all_dataset_items, sync_run_to_database


API_BASE = "https://api.apify.com/v2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync the latest scheduled/succeeded Apify shop runs into PostgreSQL.")
    parser.add_argument("--token", default=None, help="Apify API token. If omitted, APIFY_TOKEN is used.")
    parser.add_argument("--database-url", default=None, help="PostgreSQL connection string. If omitted, DATABASE_URL is used.")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parents[1] / "config" / "shops.json"),
        help="Path to shops config JSON.",
    )
    parser.add_argument(
        "--schema-path",
        default=str(DEFAULT_SCHEMA_PATH),
        help="Path to the Retail Radar PostgreSQL schema.",
    )
    parser.add_argument("--skip-schema", action="store_true", help="Skip applying the database schema.")
    parser.add_argument(
        "--shops",
        default="all",
        help="Comma-separated shop list from config, or 'all'.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = args.token or os.getenv("APIFY_TOKEN")
    if not token:
        raise RuntimeError("Provide --token or set APIFY_TOKEN.")

    database_url = args.database_url or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Provide --database-url or set DATABASE_URL.")

    config_path = Path(args.config)
    if not config_path.exists():
        raise RuntimeError(f"Config file not found: {config_path}")

    shops_config = json.loads(config_path.read_text(encoding="utf-8"))
    selected = _select_shops(shops_config, args.shops)

    from apify_client import ApifyClient

    client = ApifyClient(token)
    headers = {"Authorization": f"Bearer {token}"}
    synced = []

    import psycopg

    with psycopg.connect(database_url) as conn:
        for index, entry in enumerate(selected):
            run_info = _latest_succeeded_run(headers, entry)
            items = _all_dataset_items(client, run_info["dataset_id"])
            sync_run_to_database(
                conn=conn,
                schema_path=Path(args.schema_path),
                skip_schema=args.skip_schema or index > 0,
                shop=entry["shop"],
                actor_id=entry.get("actor_id"),
                run_info=run_info,
                items=items,
                input_json={"source": "latest_succeeded_run"},
            )
            synced.append((entry["shop"], run_info["run_id"], len(items)))

    for shop, run_id, count in synced:
        print(f"{shop}: synced {count} rows from run {run_id}")
    return 0


def _select_shops(entries: list[dict], raw_value: str) -> list[dict]:
    if raw_value.strip().lower() == "all":
        return entries
    allowed = {value.strip() for value in raw_value.split(",") if value.strip()}
    filtered = [entry for entry in entries if entry.get("shop") in allowed]
    missing = allowed - {entry.get("shop") for entry in filtered}
    if missing:
        raise RuntimeError(f"Unknown shop(s) in config: {', '.join(sorted(missing))}")
    return filtered


def _latest_succeeded_run(headers: dict[str, str], entry: dict) -> dict[str, str | None]:
    import requests

    task_id = entry.get("task_id")
    actor_id = entry.get("actor_id")

    if task_id:
        endpoint = f"{API_BASE}/actor-tasks/{quote(str(task_id), safe='')}/runs"
    elif actor_id:
        endpoint = f"{API_BASE}/acts/{quote(str(actor_id), safe='')}/runs"
    else:
        raise RuntimeError(f"Config for shop {entry.get('shop')} must contain actor_id or task_id.")

    response = requests.get(
        endpoint,
        headers=headers,
        params={"status": "SUCCEEDED", "desc": 1, "limit": 1},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    items = ((payload.get("data") or {}).get("items")) or []
    if not items:
        raise RuntimeError(f"No SUCCEEDED runs found for shop {entry.get('shop')}.")

    run = items[0]
    dataset_id = run.get("defaultDatasetId") or run.get("default_dataset_id")
    run_id = run.get("id")
    if not dataset_id or not run_id:
        raise RuntimeError(f"Run payload missing id or defaultDatasetId for shop {entry.get('shop')}.")

    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "status": run.get("status"),
        "started_at": run.get("startedAt") or run.get("started_at"),
        "finished_at": run.get("finishedAt") or run.get("finished_at"),
        "actor_id": actor_id,
    }


if __name__ == "__main__":
    raise SystemExit(main())
