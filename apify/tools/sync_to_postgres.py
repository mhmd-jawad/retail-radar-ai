from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eep.apify_ingest import DEFAULT_SCHEMA_PATH, sync_items_to_retail_core


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Apify actor output into the Retail Radar PostgreSQL schema.")
    parser.add_argument("--token", default=None, help="Apify API token. If omitted, APIFY_TOKEN is used.")
    parser.add_argument("--database-url", default=None, help="PostgreSQL connection string. If omitted, DATABASE_URL is used.")
    parser.add_argument("--actor-id", default=None, help="Actor ID in the form username/actor-name.")
    parser.add_argument("--run-id", default=None, help="Existing Apify run ID to sync.")
    parser.add_argument("--dataset-id", default=None, help="Existing dataset ID to sync directly.")
    parser.add_argument("--shop", required=True, help="Shop key, for example mikesport.")
    parser.add_argument("--sample-size", type=int, default=3, help="Used when --full is not set.")
    parser.add_argument("--full", action="store_true", help="Run full-catalog mode.")
    parser.add_argument("--max-pages", type=int, default=None, help="Optional page cap for debugging.")
    parser.add_argument(
        "--schema-path",
        default=str(DEFAULT_SCHEMA_PATH),
        help="Path to the Retail Radar PostgreSQL schema.",
    )
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="Skip applying the database schema before syncing records.",
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

    from apify_client import ApifyClient

    client = ApifyClient(token)
    run_info = _resolve_run(client, args)
    items = _all_dataset_items(client, str(run_info["dataset_id"]))
    input_json = {
        "full": args.full,
        "sampleSize": args.sample_size,
        "maxPages": args.max_pages,
    }

    import psycopg

    with psycopg.connect(database_url) as conn:
        result = sync_run_to_database(
            conn=conn,
            schema_path=Path(args.schema_path),
            skip_schema=args.skip_schema,
            shop=args.shop,
            actor_id=args.actor_id or _field(run_info, "actor_id", "actorId"),
            run_info=run_info,
            items=items,
            input_json=input_json,
        )

    print(f"Synced {result.item_count} rows into PostgreSQL intel.* tables for {result.shop}")
    print(f"Run ID: {result.apify_run_id}")
    print(f"Dataset ID: {result.apify_dataset_id}")
    print(f"DB run ID: {result.run_db_id}")
    return 0


def sync_run_to_database(
    *,
    conn: Any,
    schema_path: Path,
    skip_schema: bool,
    shop: str,
    actor_id: str | None,
    run_info: dict[str, Any],
    items: list[dict[str, Any]],
    input_json: dict[str, Any],
):
    return sync_items_to_retail_core(
        conn=conn,
        schema_path=schema_path,
        skip_schema=skip_schema,
        shop=shop,
        actor_id=actor_id,
        run_info=run_info,
        items=items,
        raw_payload={"source": "sync_to_postgres", "input": input_json},
    )


def _resolve_run(client: Any, args: argparse.Namespace) -> dict[str, Any]:
    dataset_id = None
    run_id = args.run_id
    status = None
    started_at = None
    finished_at = None
    actor_id = args.actor_id

    if args.dataset_id:
        dataset_id = args.dataset_id
        run_id = f"dataset:{args.dataset_id}"
        status = "DATASET_ONLY"
    elif args.run_id:
        run = client.run(args.run_id).get()
        dataset_id = _field(run, "defaultDatasetId", "default_dataset_id")
        run_id = _field(run, "id") or args.run_id
        status = _field(run, "status")
        started_at = _field(run, "startedAt", "started_at")
        finished_at = _field(run, "finishedAt", "finished_at")
        actor_id = actor_id or _field(run, "actId", "actorId", "actor_id")
    else:
        if not args.actor_id:
            raise RuntimeError("Provide --actor-id, --run-id, or --dataset-id.")
        run_input = {
            "full": args.full,
            "sampleSize": args.sample_size,
            "saveJsonToKeyValueStore": True,
            "saveCsvToKeyValueStore": True,
            "saveSummaryToKeyValueStore": True,
        }
        if args.max_pages is not None:
            run_input["maxPages"] = args.max_pages
        run = client.actor(args.actor_id).call(run_input=run_input)
        if run is None:
            raise RuntimeError("Actor call returned no run object.")
        dataset_id = _field(run, "defaultDatasetId", "default_dataset_id")
        run_id = _field(run, "id")
        status = _field(run, "status")
        started_at = _field(run, "startedAt", "started_at")
        finished_at = _field(run, "finishedAt", "finished_at")

    if not dataset_id:
        raise RuntimeError(f"Unable to resolve dataset ID for run {run_id or '<unknown>'}.")

    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "actor_id": actor_id,
    }


def _all_dataset_items(client: Any, dataset_id: str) -> list[dict[str, Any]]:
    dataset_client = client.dataset(dataset_id)
    items: list[dict[str, Any]] = []
    offset = 0
    limit = 1000

    while True:
        page = dataset_client.list_items(clean=True, offset=offset, limit=limit)
        page_items = list(page.items)
        if not page_items:
            break
        items.extend(page_items)
        if len(page_items) < limit:
            break
        offset += limit
    return items


def _field(payload: Any, *names: str):
    for name in names:
        if isinstance(payload, dict) and name in payload:
            return payload[name]
        if hasattr(payload, name):
            return getattr(payload, name)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
