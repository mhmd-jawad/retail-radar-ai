from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import os

from apify_client import ApifyClient


SCRAPED_PRODUCT_FIELDS = [
    "competitor_product_id",
    "competitor_name",
    "style_code",
    "sku_id",
    "brand_name",
    "product_name",
    "category",
    "gender_target",
    "competitor_price",
    "competitor_sale_price",
    "discount_pct",
    "is_on_sale",
    "availability",
    "currency",
    "sizes_available",
    "source_url",
    "scraped_at",
    "data_valid",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an Apify actor and sync its dataset into this repo.")
    parser.add_argument("--token", default=None, help="Apify API token. If omitted, APIFY_TOKEN is used.")
    parser.add_argument("--actor-id", default=None, help="Actor ID in the form username/actor-name.")
    parser.add_argument("--run-id", default=None, help="Existing Apify run ID to download instead of starting a new run.")
    parser.add_argument("--dataset-id", default=None, help="Existing dataset ID to download directly.")
    parser.add_argument("--shop", required=True, help="Local shop key, e.g. mikesport.")
    parser.add_argument("--sample-size", type=int, default=3, help="Used when --full is not set.")
    parser.add_argument("--full", action="store_true", help="Run full-catalog mode.")
    parser.add_argument("--max-pages", type=int, default=None, help="Optional page cap for debugging.")
    parser.add_argument(
        "--output-root",
        default="scraping/data/output",
        help="Repo-relative directory where records.json/csv/metadata.json should be written.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = args.token or os.getenv("APIFY_TOKEN")
    if not token:
        raise RuntimeError("Provide --token or set APIFY_TOKEN in your environment.")

    client = ApifyClient(token)

    dataset_id = None
    run_id = args.run_id
    status = None

    if args.dataset_id:
        dataset_id = args.dataset_id
    elif args.run_id:
        run = client.run(args.run_id).get()
        dataset_id = _field(run, "defaultDatasetId", "default_dataset_id")
        run_id = _field(run, "id") or args.run_id
        status = _field(run, "status")
    else:
        if not args.actor_id:
            raise RuntimeError("Provide --actor-id when you want the script to start a new Actor run.")

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

    if not dataset_id:
        raise RuntimeError(f"Run {run_id or '<unknown>'} did not return a default dataset ID.")

    items = _all_dataset_items(client, dataset_id)
    output_dir = Path(args.output_root) / args.shop
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "records.json"
    csv_path = output_dir / "records.csv"
    metadata_path = output_dir / "metadata.json"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(items, handle, indent=2, ensure_ascii=True)

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCRAPED_PRODUCT_FIELDS)
        writer.writeheader()
        for item in items:
            row = {field: item.get(field) for field in SCRAPED_PRODUCT_FIELDS}
            if isinstance(row.get("sizes_available"), list):
                row["sizes_available"] = json.dumps(row["sizes_available"], ensure_ascii=True)
            writer.writerow(row)

    metadata = {
        "shop": args.shop,
        "actor_id": args.actor_id,
        "run_id": run_id,
        "status": status,
        "dataset_id": dataset_id,
        "item_count": len(items),
        "valid_count": sum(bool(item.get("data_valid")) for item in items),
        "downloaded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "records_json": str(json_path),
        "records_csv": str(csv_path),
    }
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=True)

    print(f"Synced {len(items)} items into {output_dir}")
    print(f"Run ID: {run_id}")
    print(f"Dataset ID: {dataset_id}")
    return 0


def _field(payload, *names):
    for name in names:
        if isinstance(payload, dict) and name in payload:
            return payload[name]
        if hasattr(payload, name):
            return getattr(payload, name)
    return None


def _all_dataset_items(client: ApifyClient, dataset_id: str) -> list[dict]:
    dataset_client = client.dataset(dataset_id)
    items: list[dict] = []
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


if __name__ == "__main__":
    raise SystemExit(main())
