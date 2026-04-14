from __future__ import annotations

import json
import shutil
from pathlib import Path
from textwrap import dedent


REPO_ROOT = Path(__file__).resolve().parents[1]
APIFY_ROOT = REPO_ROOT / "apify"
TOOLS_ROOT = APIFY_ROOT / "tools"
ACTORS_ROOT = APIFY_ROOT / "actors"

SHOPS = {
    "adidas_lb": {
        "actor_name": "retail-radar-adidas-lb-scraper",
        "title": "Retail Radar - adidas Lebanon Scraper",
        "base_url": "https://www.adidas.com.lb",
    },
    "mikesport": {
        "actor_name": "retail-radar-mikesport-scraper",
        "title": "Retail Radar - MikeSport Lebanon Scraper",
        "base_url": "https://lb.mikesport.com",
    },
    "tchooz": {
        "actor_name": "retail-radar-tchooz-scraper",
        "title": "Retail Radar - Tchooz Shoes Scraper",
        "base_url": "https://tchoozshoes.com",
    },
    "shoesworld": {
        "actor_name": "retail-radar-shoesworld-scraper",
        "title": "Retail Radar - ShoesWorld Lebanon Scraper",
        "base_url": "https://www.shoesworldlb.com",
    },
    "citysport": {
        "actor_name": "retail-radar-citysport-scraper",
        "title": "Retail Radar - CitySport Scraper",
        "base_url": "https://www.citysport-lb.com",
    },
    "kix": {
        "actor_name": "retail-radar-kix-scraper",
        "title": "Retail Radar - KIX Lebanon Scraper",
        "base_url": "https://kixlb.com",
    },
    "marka_store": {
        "actor_name": "retail-radar-marka-store-scraper",
        "title": "Retail Radar - Marka Store Lebanon Scraper",
        "base_url": "https://markastorelb.com",
    },
}

ROOT_GITIGNORE = dedent(
    """
    **/.venv/
    **/storage/
    **/__pycache__/
    **/.pytest_cache/
    """
).lstrip()

ROOT_README = dedent(
    """
    # Apify deployment scaffold for the retail scrapers

    This folder packages the working scraper logic from the repo into Apify-friendly Python Actors.

    ## Layout

    - `actors/<shop>/` - one Actor folder per store
    - `tools/run_and_sync.py` - starts a cloud Actor run and writes the results back into `scraping/data/output/<shop>/`

    ## Actor folders

    - `actors/adidas_lb`
    - `actors/mikesport`
    - `actors/tchooz`
    - `actors/shoesworld`
    - `actors/citysport`
    - `actors/kix`
    - `actors/marka_store`

    ## Recommended workflow

    1. Develop in VS Code from this repo.
    2. Open one Actor folder, for example `apify/actors/mikesport`.
    3. Install the Apify CLI.
    4. Log in with `apify login`.
    5. Push that actor with `apify push`.
    6. Run it in Apify Console or with the API.
    7. Pull the dataset back into this repo with `python apify/tools/run_and_sync.py ...`.

    Each actor folder is self-contained, so you can run `apify push` directly inside that actor directory.
    """
).lstrip()

TOOL_REQUIREMENTS = dedent(
    """
    apify-client>=2.5.0,<3.0.0
    """
).lstrip()

RUN_AND_SYNC_SCRIPT = dedent(
    """
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
    """
).lstrip()

ACTOR_MAIN = dedent(
    """
    from __future__ import annotations

    import csv
    import importlib
    import io
    import os
    import sys
    from pathlib import Path

    from apify import Actor


    def _bootstrap_shared_path() -> None:
        shared_override = os.getenv("APIFY_SHARED_SRC")
        candidates = []
        if shared_override:
            candidates.append(Path(shared_override))
        candidates.append(Path(__file__).resolve().parents[1] / "shared_src")
        candidates.append(Path(__file__).resolve().parents[3] / "shared_src")

        for candidate in candidates:
            if candidate.exists():
                candidate_str = str(candidate.resolve())
                if candidate_str not in sys.path:
                    sys.path.insert(0, candidate_str)
                return

        raise RuntimeError("Could not locate shared scraper package for this actor.")


    _bootstrap_shared_path()

    from scraping.common.models import SCRAPED_PRODUCT_FIELDS
    from scraping.common.normalization import has_real_identifier


    def _store_name() -> str:
        store_name = os.getenv("STORE_NAME")
        if store_name:
            return store_name

        inferred = Path(__file__).resolve().parents[1].name
        if inferred:
            return inferred
        raise RuntimeError("STORE_NAME environment variable is required.")


    def _load_scrape_callable(store_name: str):
        module = importlib.import_module(f"scraping.shops.{store_name}.scraper")
        scrape = getattr(module, "scrape", None)
        if scrape is None:
            raise RuntimeError(f"scraping.shops.{store_name}.scraper has no scrape() function.")
        return scrape


    def _positive_int(value, *, field_name: str, allow_none: bool = True):
        if value in (None, ""):
            if allow_none:
                return None
            raise ValueError(f"{field_name} is required.")

        parsed = int(value)
        if parsed <= 0:
            raise ValueError(f"{field_name} must be greater than zero.")
        return parsed


    def _records_to_csv(records) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=SCRAPED_PRODUCT_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())
        return buffer.getvalue()


    async def _consume_records(records_iterable, *, chunk_size: int = 100):
        records = []
        items: list[dict] = []
        chunk: list[dict] = []

        for record in records_iterable:
            records.append(record)
            item = record.to_dict()
            items.append(item)
            chunk.append(item)
            if len(chunk) >= chunk_size:
                await Actor.push_data(chunk)
                chunk = []

        if chunk:
            await Actor.push_data(chunk)

        return records, items


    def _build_summary(store_name: str, records, *, full: bool, sample_size: int | None, max_pages: int | None) -> dict:
        return {
            "shop": store_name,
            "mode": "full" if full else "sample",
            "sample_size": sample_size,
            "max_pages": max_pages,
            "record_count": len(records),
            "valid_count": sum(1 for record in records if record.data_valid),
            "style_code_count": sum(1 for record in records if has_real_identifier(record.style_code)),
            "sku_id_count": sum(1 for record in records if has_real_identifier(record.sku_id)),
            "sale_count": sum(1 for record in records if record.is_on_sale),
            "out_of_stock_count": sum(1 for record in records if record.availability == "out_of_stock"),
        }


    async def main() -> None:
        async with Actor:
            store_name = _store_name()
            actor_input = await Actor.get_input() or {}
            full = bool(actor_input.get("full", False))
            sample_size = _positive_int(actor_input.get("sampleSize", 3), field_name="sampleSize", allow_none=False)
            max_pages = _positive_int(actor_input.get("maxPages"), field_name="maxPages", allow_none=True)
            max_products = None if full else sample_size
            scrape = _load_scrape_callable(store_name)

            await Actor.set_status_message(
                f"Scraping {store_name} in {'full' if full else 'sample'} mode",
            )
            records, items = await _consume_records(scrape(max_products=max_products, max_pages=max_pages))
            summary = _build_summary(
                store_name,
                records,
                full=full,
                sample_size=sample_size,
                max_pages=max_pages,
            )

            if actor_input.get("saveSummaryToKeyValueStore", True):
                await Actor.set_value("OUTPUT_SUMMARY", summary)
            if actor_input.get("saveJsonToKeyValueStore", True):
                await Actor.set_value("OUTPUT_JSON", items)
            if actor_input.get("saveCsvToKeyValueStore", True):
                await Actor.set_value(
                    "OUTPUT_CSV",
                    _records_to_csv(records),
                    content_type="text/csv; charset=utf-8",
                )

            await Actor.set_status_message(
                f"Finished {store_name}: {len(records)} records, {summary['valid_count']} valid",
                is_terminal=True,
            )
    """
).lstrip()

ACTOR_MAIN_ENTRY = dedent(
    """
    from __future__ import annotations

    import asyncio

    from .main import main


    if __name__ == "__main__":
        asyncio.run(main())
    """
).lstrip()

ACTOR_REQUIREMENTS = dedent(
    """
    apify>=3.3.2,<4.0.0
    requests>=2.32.0,<3.0.0
    """
).lstrip()

DEFAULT_INPUT = {
    "full": False,
    "sampleSize": 3,
    "saveJsonToKeyValueStore": True,
    "saveCsvToKeyValueStore": True,
    "saveSummaryToKeyValueStore": True,
}

ACTOR_DOCKERIGNORE = dedent(
    """
    .venv
    storage
    __pycache__
    *.pyc
    .pytest_cache
    """
).lstrip()


def actor_json(shop: str, actor_name: str, title: str) -> str:
    payload = {
        "actorSpecification": 1,
        "name": actor_name,
        "title": title,
        "version": "0.1",
        "buildTag": "latest",
        "dockerfile": "./Dockerfile",
        "readme": "./README.md",
        "input": "./INPUT_SCHEMA.json",
        "environmentVariables": {
            "STORE_NAME": shop,
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"


def input_schema_json(shop: str, title: str, base_url: str) -> str:
    payload = {
        "title": f"Input schema for {title}",
        "description": (
            f"Run the {shop} scraper from the Retail Radar repo. "
            f"The underlying store endpoint starts from {base_url}."
        ),
        "type": "object",
        "schemaVersion": 1,
        "properties": {
            "full": {
                "title": "Full catalog mode",
                "type": "boolean",
                "description": "If true, scrape the full supported catalog. If false, sampleSize is used.",
                "default": False,
            },
            "sampleSize": {
                "title": "Sample size",
                "type": "integer",
                "description": "How many products to scrape when full catalog mode is off.",
                "default": 3,
                "minimum": 1,
            },
            "maxPages": {
                "title": "Max pages",
                "type": "integer",
                "description": "Optional adapter page or sitemap cap for debugging.",
                "minimum": 1,
                "nullable": True,
            },
            "saveJsonToKeyValueStore": {
                "title": "Save JSON file",
                "type": "boolean",
                "description": "Save all records into OUTPUT_JSON in the default key-value store.",
                "default": True,
            },
            "saveCsvToKeyValueStore": {
                "title": "Save CSV file",
                "type": "boolean",
                "description": "Save all records into OUTPUT_CSV in the default key-value store.",
                "default": True,
            },
            "saveSummaryToKeyValueStore": {
                "title": "Save summary",
                "type": "boolean",
                "description": "Save counts and run summary into OUTPUT_SUMMARY in the default key-value store.",
                "default": True,
            },
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"


def dockerfile(shop: str) -> str:
    return dedent(
        f"""
        FROM python:3.11-slim

        ENV PYTHONUNBUFFERED=1 \\
            PYTHONDONTWRITEBYTECODE=1 \\
            PIP_NO_CACHE_DIR=1 \\
            APIFY_SHARED_SRC=/home/myuser/shared_src \\
            STORE_NAME={shop}

        WORKDIR /home/myuser

        COPY requirements.txt /tmp/requirements.txt
        RUN python -m pip install --upgrade pip \\
            && python -m pip install -r /tmp/requirements.txt

        COPY shared_src /home/myuser/shared_src
        COPY src /home/myuser/src

        CMD ["python", "-m", "src"]
        """
    ).lstrip()


def actor_readme(shop: str, title: str, base_url: str) -> str:
    return dedent(
        f"""
        # {title}

        This Apify Actor wraps the existing Retail Radar scraper for `{shop}`.

        ## Source store

        - Base URL: `{base_url}`

        ## Output

        The Actor writes normalized product records to:

        - the default dataset
        - `OUTPUT_SUMMARY` in the default key-value store
        - `OUTPUT_JSON` in the default key-value store
        - `OUTPUT_CSV` in the default key-value store

        ## Local test

        1. Create a virtual environment.
        2. Install `requirements.txt`.
        3. Run `python -m src` from this actor folder.

        ## Cloud deployment

        1. Run `apify login`.
        2. Run `apify push` from this actor folder.
        3. Start the Actor in Apify Console with the generated input UI.
        """
    ).lstrip()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _copy_shared_scraper_package(target_root: Path) -> None:
    shared_src_root = target_root / "shared_src" / "scraping"
    if shared_src_root.exists():
        shutil.rmtree(shared_src_root)
    shared_src_root.mkdir(parents=True, exist_ok=True)

    source_scraping_root = REPO_ROOT / "scraping"
    shutil.copy2(source_scraping_root / "__init__.py", shared_src_root / "__init__.py")
    shutil.copytree(source_scraping_root / "common", shared_src_root / "common", dirs_exist_ok=True)
    shutil.copytree(source_scraping_root / "shops", shared_src_root / "shops", dirs_exist_ok=True)


def build_actor_folders() -> None:
    ACTORS_ROOT.mkdir(parents=True, exist_ok=True)

    for shop, meta in SHOPS.items():
        actor_root = ACTORS_ROOT / shop
        actor_root.mkdir(parents=True, exist_ok=True)
        _copy_shared_scraper_package(actor_root)

        write_text(actor_root / ".actor" / "actor.json", actor_json(shop, meta["actor_name"], meta["title"]))
        write_text(
            actor_root / ".actor" / "INPUT_SCHEMA.json",
            input_schema_json(shop, meta["title"], meta["base_url"]),
        )
        write_text(actor_root / "Dockerfile", dockerfile(shop))
        write_text(actor_root / ".dockerignore", ACTOR_DOCKERIGNORE)
        write_text(actor_root / ".gitignore", ACTOR_DOCKERIGNORE)
        write_text(actor_root / "requirements.txt", ACTOR_REQUIREMENTS)
        write_text(actor_root / "README.md", actor_readme(shop, meta["title"], meta["base_url"]))
        write_text(actor_root / "src" / "__main__.py", ACTOR_MAIN_ENTRY)
        write_text(actor_root / "src" / "main.py", ACTOR_MAIN)
        write_json(actor_root / "storage" / "key_value_stores" / "default" / "INPUT.json", DEFAULT_INPUT)


def build_tooling() -> None:
    TOOLS_ROOT.mkdir(parents=True, exist_ok=True)
    write_text(TOOLS_ROOT / "requirements.txt", TOOL_REQUIREMENTS)
    write_text(TOOLS_ROOT / "run_and_sync.py", RUN_AND_SYNC_SCRIPT)


def build_root_files() -> None:
    write_text(APIFY_ROOT / ".gitignore", ROOT_GITIGNORE)
    write_text(APIFY_ROOT / "README.md", ROOT_README)


def main() -> int:
    APIFY_ROOT.mkdir(parents=True, exist_ok=True)
    build_actor_folders()
    build_tooling()
    build_root_files()
    print(f"Apify scaffold generated under {APIFY_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
