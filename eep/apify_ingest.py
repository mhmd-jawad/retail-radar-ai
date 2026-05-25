from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA_PATH = ROOT / "infra" / "postgres" / "001_intel_scraping.sql"
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/retail_radar"
APIFY_API_BASE = "https://api.apify.com/v2"
MISSING_IDENTIFIER = "does_not_exist"


@dataclass(frozen=True)
class IngestResult:
    shop: str
    run_db_id: int
    apify_run_id: str
    apify_dataset_id: str | None
    item_count: int
    valid_count: int
    snapshot_count: int
    latest_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def apify_token() -> str | None:
    return os.environ.get("APIFY_TOKEN")


def extract_actor_run_id(payload: dict[str, Any]) -> str | None:
    """Support the common Apify webhook payload shapes."""
    event_data = payload.get("eventData") if isinstance(payload.get("eventData"), dict) else {}
    resource = payload.get("resource") if isinstance(payload.get("resource"), dict) else {}
    candidates = (
        event_data.get("actorRunId"),
        payload.get("actorRunId"),
        resource.get("actorRunId"),
        resource.get("id"),
    )
    for value in candidates:
        if value:
            return str(value)
    return None


def fetch_run_info(actor_run_id: str, token: str) -> dict[str, Any]:
    payload = _apify_get(f"actor-runs/{quote(actor_run_id, safe='')}", token)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    dataset_id = data.get("defaultDatasetId") or data.get("default_dataset_id")
    run_id = data.get("id") or actor_run_id
    if not dataset_id:
        raise RuntimeError(f"Apify run {actor_run_id} has no default dataset id.")
    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "status": data.get("status"),
        "started_at": data.get("startedAt") or data.get("started_at"),
        "finished_at": data.get("finishedAt") or data.get("finished_at"),
        "actor_id": data.get("actId") or data.get("actorId") or data.get("actor_id"),
    }


def fetch_dataset_items(dataset_id: str, token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    limit = 1000
    while True:
        query = urlencode({"clean": "true", "offset": offset, "limit": limit})
        page = _apify_get(f"datasets/{quote(dataset_id, safe='')}/items?{query}", token)
        if not isinstance(page, list):
            raise RuntimeError(f"Unexpected Apify dataset response for {dataset_id}.")
        if not page:
            break
        items.extend([item for item in page if isinstance(item, dict)])
        if len(page) < limit:
            break
        offset += limit
    return items


def sync_apify_run_to_retail_core(
    *,
    shop: str,
    actor_run_id: str,
    token: str,
    raw_webhook_payload: dict[str, Any] | None = None,
    db_url: str | None = None,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    skip_schema: bool = False,
) -> IngestResult:
    run_info = fetch_run_info(actor_run_id, token)
    items = fetch_dataset_items(str(run_info["dataset_id"]), token)
    import psycopg

    with psycopg.connect(db_url or database_url()) as conn:
        return sync_items_to_retail_core(
            conn=conn,
            shop=shop,
            actor_id=run_info.get("actor_id"),
            run_info=run_info,
            items=items,
            raw_payload=raw_webhook_payload,
            schema_path=schema_path,
            skip_schema=skip_schema,
        )


def sync_items_to_retail_core(
    *,
    conn: Any,
    shop: str,
    actor_id: str | None,
    run_info: dict[str, Any],
    items: list[dict[str, Any]],
    raw_payload: dict[str, Any] | None = None,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    skip_schema: bool = False,
) -> IngestResult:
    if not skip_schema:
        _apply_schema(conn, schema_path)

    normalized_shop = _clean_shop(shop)
    run_id = _clean_run_id(run_info)
    dataset_id = _text(run_info.get("dataset_id") or run_info.get("defaultDatasetId"))
    actor_id = _text(actor_id or run_info.get("actor_id") or run_info.get("actorId"))

    _upsert_shop(conn, normalized_shop, actor_id)
    run_db_id = _upsert_run(conn, normalized_shop, actor_id, run_id, dataset_id, run_info, items, raw_payload)
    snapshot_count = _upsert_snapshots(conn, normalized_shop, run_db_id, items)
    latest_count = _upsert_latest(conn, normalized_shop, run_db_id, items)
    conn.commit()

    return IngestResult(
        shop=normalized_shop,
        run_db_id=run_db_id,
        apify_run_id=run_id,
        apify_dataset_id=dataset_id,
        item_count=len(items),
        valid_count=sum(_bool(item.get("data_valid"), default=True) for item in items),
        snapshot_count=snapshot_count,
        latest_count=latest_count,
    )


def _apify_get(path_and_query: str, token: str) -> Any:
    url = f"{APIFY_API_BASE}/{path_and_query}"
    request = Request(url, headers={"Authorization": f"Bearer {token}"})
    with urlopen(request, timeout=90) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def _apply_schema(conn: Any, schema_path: Path) -> None:
    if not schema_path.exists():
        raise RuntimeError(f"Schema file not found: {schema_path}")
    with conn.cursor() as cur:
        cur.execute(schema_path.read_text(encoding="utf-8"))
    conn.commit()


def _upsert_shop(conn: Any, shop: str, actor_id: str | None) -> None:
    shop_name = shop.replace("_", " ").title()
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into intel.shops (shop_code, shop_name, apify_actor_id)
            values (%s, %s, %s)
            on conflict (shop_code) do update
            set
                shop_name = coalesce(nullif(intel.shops.shop_name, ''), excluded.shop_name),
                apify_actor_id = coalesce(excluded.apify_actor_id, intel.shops.apify_actor_id),
                is_active = true,
                updated_at = now()
            """,
            (shop, shop_name, actor_id),
        )


def _upsert_run(
    conn: Any,
    shop: str,
    actor_id: str | None,
    run_id: str,
    dataset_id: str | None,
    run_info: dict[str, Any],
    items: list[dict[str, Any]],
    raw_payload: dict[str, Any] | None,
) -> int:
    payload = raw_payload or {}
    if run_info:
        payload = {**payload, "_run_info": run_info}
    status = _text(run_info.get("status")) or "SUCCEEDED"
    started_at = _parse_timestamp(run_info.get("started_at") or run_info.get("startedAt"))
    finished_at = _parse_timestamp(run_info.get("finished_at") or run_info.get("finishedAt"))
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into intel.scrape_runs (
                shop_code,
                apify_run_id,
                apify_dataset_id,
                status,
                started_at,
                finished_at,
                item_count,
                ingest_status,
                ingest_error,
                raw_webhook_payload
            )
            values (%s, %s, %s, %s, %s, %s, %s, 'succeeded', null, %s)
            on conflict (apify_run_id) do update
            set
                shop_code = excluded.shop_code,
                apify_dataset_id = excluded.apify_dataset_id,
                status = excluded.status,
                started_at = coalesce(excluded.started_at, intel.scrape_runs.started_at),
                finished_at = coalesce(excluded.finished_at, intel.scrape_runs.finished_at),
                item_count = excluded.item_count,
                ingest_status = 'succeeded',
                ingest_error = null,
                raw_webhook_payload = excluded.raw_webhook_payload
            returning id
            """,
            (
                shop,
                run_id,
                dataset_id,
                status,
                started_at,
                finished_at,
                len(items),
                _jsonb(payload),
            ),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("Failed to upsert intel.scrape_runs.")
    return int(row[0])


def _upsert_snapshots(conn: Any, shop: str, run_db_id: int, items: list[dict[str, Any]]) -> int:
    rows = [_row_tuple(shop, run_db_id, item, latest=False) for item in items]
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into intel.competitor_product_snapshots (
                shop_code,
                scrape_run_id,
                snapshot_at,
                product_key,
                competitor_product_id,
                style_code,
                sku_id,
                brand_name,
                product_name,
                category,
                gender_target,
                competitor_price,
                competitor_sale_price,
                discount_pct,
                is_on_sale,
                availability,
                currency,
                sizes_available,
                source_url,
                data_valid,
                raw_record
            )
            values (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            on conflict (scrape_run_id, product_key) do update
            set
                snapshot_at = excluded.snapshot_at,
                competitor_product_id = excluded.competitor_product_id,
                style_code = excluded.style_code,
                sku_id = excluded.sku_id,
                brand_name = excluded.brand_name,
                product_name = excluded.product_name,
                category = excluded.category,
                gender_target = excluded.gender_target,
                competitor_price = excluded.competitor_price,
                competitor_sale_price = excluded.competitor_sale_price,
                discount_pct = excluded.discount_pct,
                is_on_sale = excluded.is_on_sale,
                availability = excluded.availability,
                currency = excluded.currency,
                sizes_available = excluded.sizes_available,
                source_url = excluded.source_url,
                data_valid = excluded.data_valid,
                raw_record = excluded.raw_record
            """,
            rows,
        )
    return len(rows)


def _upsert_latest(conn: Any, shop: str, run_db_id: int, items: list[dict[str, Any]]) -> int:
    rows = [_row_tuple(shop, run_db_id, item, latest=True) for item in items]
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into intel.competitor_products_latest (
                shop_code,
                product_key,
                last_scrape_run_id,
                first_seen_at,
                last_seen_at,
                competitor_product_id,
                style_code,
                sku_id,
                brand_name,
                product_name,
                category,
                gender_target,
                competitor_price,
                competitor_sale_price,
                discount_pct,
                is_on_sale,
                availability,
                currency,
                sizes_available,
                source_url,
                data_valid,
                raw_record
            )
            values (
                %s, %s, %s, now(), %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            on conflict (shop_code, product_key) do update
            set
                last_scrape_run_id = excluded.last_scrape_run_id,
                last_seen_at = excluded.last_seen_at,
                competitor_product_id = excluded.competitor_product_id,
                style_code = excluded.style_code,
                sku_id = excluded.sku_id,
                brand_name = excluded.brand_name,
                product_name = excluded.product_name,
                category = excluded.category,
                gender_target = excluded.gender_target,
                competitor_price = excluded.competitor_price,
                competitor_sale_price = excluded.competitor_sale_price,
                discount_pct = excluded.discount_pct,
                is_on_sale = excluded.is_on_sale,
                availability = excluded.availability,
                currency = excluded.currency,
                sizes_available = excluded.sizes_available,
                source_url = excluded.source_url,
                data_valid = excluded.data_valid,
                raw_record = excluded.raw_record
            """,
            rows,
        )
    return len(rows)


def _row_tuple(shop: str, run_db_id: int, item: dict[str, Any], *, latest: bool) -> tuple[Any, ...]:
    scraped_at = _parse_timestamp(item.get("scraped_at")) or datetime.now(timezone.utc)
    product_key = _product_key(shop, item)
    competitor_product_id = _optional_identifier(item.get("competitor_product_id"))
    style_code = _optional_identifier(item.get("style_code"))
    sku_id = _optional_identifier(item.get("sku_id"))
    common = (
        competitor_product_id,
        style_code,
        sku_id,
        _text(item.get("brand_name")),
        _text(item.get("product_name")) or "Unknown Product",
        _text(item.get("category")),
        _text(item.get("gender_target")),
        _number(item.get("competitor_price")),
        _number(item.get("competitor_sale_price")),
        _number(item.get("discount_pct")),
        _bool(item.get("is_on_sale"), default=False),
        _text(item.get("availability")),
        _text(item.get("currency")) or "USD",
        _jsonb(_list(item.get("sizes_available"))),
        _text(item.get("source_url")),
        _bool(item.get("data_valid"), default=True),
        _jsonb(item),
    )
    if latest:
        return (shop, product_key, run_db_id, scraped_at, *common)
    return (shop, run_db_id, scraped_at, product_key, *common)


def _clean_shop(value: str) -> str:
    cleaned = _text(value)
    if not cleaned:
        raise RuntimeError("Shop is required for Apify ingestion.")
    return cleaned


def _clean_run_id(run_info: dict[str, Any]) -> str:
    run_id = _text(run_info.get("run_id") or run_info.get("id") or run_info.get("apify_run_id"))
    dataset_id = _text(run_info.get("dataset_id") or run_info.get("defaultDatasetId"))
    if run_id:
        return run_id
    if dataset_id:
        return f"dataset:{dataset_id}"
    raise RuntimeError("Apify run id or dataset id is required.")


def _product_key(shop: str, item: dict[str, Any]) -> str:
    parts = [
        shop,
        _optional_identifier(item.get("competitor_product_id")),
        _text(item.get("source_url")),
        _optional_identifier(item.get("sku_id")),
        _optional_identifier(item.get("style_code")),
        _text(item.get("product_name")),
    ]
    raw = "|".join(part or "" for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_identifier(value: Any) -> str | None:
    text = _text(value)
    if not text or text == MISSING_IDENTIFIER:
        return None
    return text


def _parse_timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def _jsonb(value: Any) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(_json_compatible(value))


def _json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_compatible(item) for item in value]
    return str(value)
