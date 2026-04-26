from __future__ import annotations

import os
import json
import threading
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "infra" / "postgres" / "001_retail_core.sql"
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/retail_radar"
DEFAULT_TENANT_SLUG = "default"
DEFAULT_STORE_CODE = "MAIN"

_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()


class DatabaseUnavailable(RuntimeError):
    pass


class InventoryItemPayload(BaseModel):
    sku_id: str = Field(min_length=1, max_length=120)
    product_name: str = Field(min_length=1, max_length=500)
    brand: str = Field(default="Unknown", max_length=200)
    category: str = Field(default="uncategorized", max_length=160)
    current_stock: int = Field(default=0, ge=0)
    retail_price_usd: float = Field(default=0, ge=0)
    cost_price_usd: float = Field(default=0, ge=0)
    barcode: str | None = Field(default=None, max_length=160)
    style_code: str | None = Field(default=None, max_length=160)
    color: str | None = Field(default=None, max_length=120)
    size: str | None = Field(default=None, max_length=120)
    gender_target: str | None = Field(default=None, max_length=120)
    season: str | None = Field(default=None, max_length=120)
    reorder_point: int = Field(default=0, ge=0)
    reorder_quantity: int = Field(default=0, ge=0)
    supplier_name: str | None = Field(default=None, max_length=240)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator(
        "sku_id",
        "product_name",
        "brand",
        "category",
        "barcode",
        "style_code",
        "color",
        "size",
        "gender_target",
        "season",
        "supplier_name",
        "notes",
        mode="before",
    )
    @classmethod
    def _clean_text(cls, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("brand", "category", mode="after")
    @classmethod
    def _defaults(cls, value: str | None, info):
        if value:
            return value
        return "Unknown" if info.field_name == "brand" else "uncategorized"


class InventoryImportPayload(BaseModel):
    mode: Literal["upsert", "replace"] = "upsert"
    items: list[InventoryItemPayload] = Field(min_length=1, max_length=5000)


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def tenant_slug() -> str:
    return os.environ.get("RETAIL_TENANT_SLUG", DEFAULT_TENANT_SLUG)


def store_code() -> str:
    return os.environ.get("RETAIL_STORE_CODE", DEFAULT_STORE_CODE)


def _import_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:  # pragma: no cover - depends on local env
        raise DatabaseUnavailable(
            "PostgreSQL driver is missing. Install eep/requirements.txt or add psycopg[binary]."
        ) from exc
    return psycopg, dict_row


@contextmanager
def _connect():
    psycopg, dict_row = _import_psycopg()
    try:
        conn = psycopg.connect(database_url(), row_factory=dict_row)
    except Exception as exc:  # pragma: no cover - depends on local DB
        raise DatabaseUnavailable(f"Cannot connect to PostgreSQL: {exc}") from exc

    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY or os.environ.get("RETAIL_AUTO_INIT_DB", "true").lower() not in {"1", "true", "yes"}:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        if not SCHEMA_PATH.exists():
            raise DatabaseUnavailable(f"Schema file not found: {SCHEMA_PATH}")
        with conn.cursor() as cur:
            cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
        _SCHEMA_READY = True


def _context(cur) -> dict[str, Any]:
    cur.execute(
        """
        select t.id as tenant_id, s.id as store_id
        from core.tenants t
        join core.stores s on s.tenant_id = t.id
        where t.slug = %s and s.code = %s and s.is_active = true
        """,
        (tenant_slug(), store_code()),
    )
    row = cur.fetchone()
    if not row:
        raise DatabaseUnavailable(
            f"Default tenant/store not found: {tenant_slug()}/{store_code()}. Run the schema first."
        )
    return row


def db_status() -> dict[str, Any]:
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                ctx = _context(cur)
                cur.execute("select count(*) as item_count from core.sku_variants where tenant_id = %s", (ctx["tenant_id"],))
                count = cur.fetchone()["item_count"]
        return {
            "connected": True,
            "database_url_hint": _safe_database_url(),
            "tenant": tenant_slug(),
            "store": store_code(),
            "item_count": int(count),
            "schema_auto_init": os.environ.get("RETAIL_AUTO_INIT_DB", "true"),
        }
    except Exception as exc:
        return {
            "connected": False,
            "database_url_hint": _safe_database_url(),
            "tenant": tenant_slug(),
            "store": store_code(),
            "error": str(exc),
        }


def list_inventory_items(search: str | None = None, limit: int = 500) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            params: list[Any] = [ctx["tenant_id"]]
            conditions = ["v.tenant_id = %s", "v.status = 'active'"]
            if search:
                search_param = f"%{search.lower()}%"
                conditions.append(
                    "("
                    "lower(v.sku_id) like %s"
                    " or lower(p.name) like %s"
                    " or lower(p.brand) like %s"
                    " or lower(coalesce(v.style_code, '')) like %s"
                    ")"
                )
                params.extend([search_param, search_param, search_param, search_param])
            params.append(limit)
            where = " and ".join(conditions)
            cur.execute(
                """
                select
                    p.id as product_id,
                    v.id as variant_id,
                    v.sku_id,
                    v.barcode,
                    v.style_code,
                    v.color,
                    v.size,
                    p.name as product_name,
                    p.brand,
                    p.category,
                    p.gender_target,
                    p.season,
                    coalesce(b.quantity_on_hand, 0) as current_stock,
                    coalesce(v.cost_price_usd, 0) as cost_price_usd,
                    coalesce(pr.amount, 0) as retail_price_usd,
                    v.reorder_point,
                    v.reorder_quantity,
                    greatest(p.updated_at, v.updated_at, coalesce(b.updated_at, v.updated_at)) as updated_at
                from core.sku_variants v
                join core.products p on p.id = v.product_id
                left join core.inventory_balances b
                    on b.variant_id = v.id and b.store_id = %s
                left join lateral (
                    select amount
                    from core.prices
                    where variant_id = v.id and price_type = 'retail' and valid_to is null
                    order by valid_from desc
                    limit 1
                ) pr on true
                where """
                + where
                + """
                order by greatest(p.updated_at, v.updated_at, coalesce(b.updated_at, v.updated_at)) desc, v.sku_id
                limit %s
                """,
                [ctx["store_id"], *params],
            )
            items = [_serialize_item(row) for row in cur.fetchall()]
    return {"items": items, "summary": _summary(items)}


def create_inventory_item(payload: InventoryItemPayload) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            item = _upsert_inventory_item(cur, ctx, payload, actor="frontend", movement_type="initial_stock")
            _audit(cur, ctx["tenant_id"], "inventory_item", item["sku_id"], "upsert", None, item)
    return item


def update_inventory_item(sku_id: str, payload: InventoryItemPayload) -> dict[str, Any]:
    data = payload.model_copy(update={"sku_id": sku_id})
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            before = _get_inventory_item(cur, ctx, sku_id)
            if not before:
                raise KeyError(sku_id)
            item = _upsert_inventory_item(cur, ctx, data, actor="frontend", movement_type="adjustment_in")
            _audit(cur, ctx["tenant_id"], "inventory_item", item["sku_id"], "update", before, item)
    return item


def archive_inventory_item(sku_id: str) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            before = _get_inventory_item(cur, ctx, sku_id)
            if not before:
                raise KeyError(sku_id)
            cur.execute(
                """
                update core.sku_variants
                set status = 'archived', updated_at = now()
                where tenant_id = %s and sku_id = %s
                """,
                (ctx["tenant_id"], sku_id),
            )
            after = {**before, "status": "archived"}
            _audit(cur, ctx["tenant_id"], "inventory_item", sku_id, "archive", before, after)
    return after


def import_inventory(payload: InventoryImportPayload) -> dict[str, Any]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            for entry in payload.items:
                item = _upsert_inventory_item(
                    cur,
                    ctx,
                    entry,
                    actor="bulk_import",
                    movement_type="full_import_adjustment",
                )
                seen.add(item["sku_id"])
                items.append(item)

            archived_count = 0
            if payload.mode == "replace":
                cur.execute(
                    """
                    update core.sku_variants
                    set status = 'archived', updated_at = now()
                    where tenant_id = %s and status = 'active' and sku_id <> all(%s)
                    """,
                    (ctx["tenant_id"], list(seen)),
                )
                archived_count = cur.rowcount

            _audit(
                cur,
                ctx["tenant_id"],
                "inventory_import",
                "bulk",
                payload.mode,
                None,
                {"imported": len(items), "archived": archived_count, "skus": sorted(seen)},
            )
    return {"imported": len(items), "archived": archived_count, "items": items, "summary": _summary(items)}


def _upsert_inventory_item(cur, ctx: dict[str, Any], payload: InventoryItemPayload, actor: str, movement_type: str) -> dict[str, Any]:
    data = payload.model_dump()
    sku_id = data["sku_id"]
    cur.execute(
        """
        select v.id as variant_id, p.id as product_id
        from core.sku_variants v
        join core.products p on p.id = v.product_id
        where v.tenant_id = %s and v.sku_id = %s
        """,
        (ctx["tenant_id"], sku_id),
    )
    existing = cur.fetchone()

    if existing:
        product_id = existing["product_id"]
        variant_id = existing["variant_id"]
        cur.execute(
            """
            update core.products
            set brand = %s, name = %s, category = %s, gender_target = %s, season = %s,
                status = 'active', updated_at = now()
            where id = %s
            """,
            (
                data["brand"],
                data["product_name"],
                data["category"],
                data["gender_target"],
                data["season"],
                product_id,
            ),
        )
        cur.execute(
            """
            update core.sku_variants
            set barcode = %s, style_code = %s, color = %s, size = %s, cost_price_usd = %s,
                reorder_point = %s, reorder_quantity = %s, status = 'active', updated_at = now()
            where id = %s
            """,
            (
                data["barcode"],
                data["style_code"],
                data["color"],
                data["size"],
                data["cost_price_usd"],
                data["reorder_point"],
                data["reorder_quantity"],
                variant_id,
            ),
        )
    else:
        cur.execute(
            """
            insert into core.products (tenant_id, brand, name, category, gender_target, season)
            values (%s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                ctx["tenant_id"],
                data["brand"],
                data["product_name"],
                data["category"],
                data["gender_target"],
                data["season"],
            ),
        )
        product_id = cur.fetchone()["id"]
        cur.execute(
            """
            insert into core.sku_variants (
                tenant_id, product_id, sku_id, barcode, style_code, color, size,
                cost_price_usd, reorder_point, reorder_quantity
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                ctx["tenant_id"],
                product_id,
                sku_id,
                data["barcode"],
                data["style_code"],
                data["color"],
                data["size"],
                data["cost_price_usd"],
                data["reorder_point"],
                data["reorder_quantity"],
            ),
        )
        variant_id = cur.fetchone()["id"]

    _set_current_price(cur, ctx["tenant_id"], variant_id, data["retail_price_usd"])
    _set_current_stock(cur, ctx, variant_id, data["current_stock"], data["cost_price_usd"], actor, movement_type)
    item = _get_inventory_item(cur, ctx, sku_id)
    if not item:
        raise RuntimeError(f"Failed to load upserted SKU {sku_id}")
    return item


def _set_current_price(cur, tenant_id: Any, variant_id: Any, amount: float) -> None:
    cur.execute(
        """
        select id, amount
        from core.prices
        where variant_id = %s and price_type = 'retail' and valid_to is null
        for update
        """,
        (variant_id,),
    )
    current = cur.fetchone()
    if current and float(current["amount"]) == float(amount):
        return
    if current:
        cur.execute("update core.prices set valid_to = now() where id = %s", (current["id"],))
    cur.execute(
        """
        insert into core.prices (tenant_id, variant_id, price_type, currency, amount)
        values (%s, %s, 'retail', 'USD', %s)
        """,
        (tenant_id, variant_id, amount),
    )


def _set_current_stock(
    cur,
    ctx: dict[str, Any],
    variant_id: Any,
    desired_stock: int,
    unit_cost: float,
    actor: str,
    movement_type: str,
) -> None:
    cur.execute(
        """
        select id, quantity_on_hand
        from core.inventory_balances
        where tenant_id = %s and store_id = %s and variant_id = %s
        for update
        """,
        (ctx["tenant_id"], ctx["store_id"], variant_id),
    )
    balance = cur.fetchone()
    current_stock = int(balance["quantity_on_hand"]) if balance else 0
    delta = int(desired_stock) - current_stock

    if not balance:
        cur.execute(
            """
            insert into core.inventory_balances (tenant_id, store_id, variant_id, quantity_on_hand)
            values (%s, %s, %s, 0)
            """,
            (ctx["tenant_id"], ctx["store_id"], variant_id),
        )

    if delta == 0:
        return

    movement = movement_type
    if movement_type == "adjustment_in" and delta < 0:
        movement = "adjustment_out"

    cur.execute(
        """
        insert into core.inventory_movements (
            tenant_id, store_id, variant_id, movement_type, quantity_delta,
            unit_cost_usd, reference_type, notes, created_by
        )
        values (%s, %s, %s, %s, %s, %s, 'inventory_ui', 'Set current stock from frontend', %s)
        """,
        (ctx["tenant_id"], ctx["store_id"], variant_id, movement, delta, unit_cost, actor),
    )
    cur.execute(
        """
        update core.inventory_balances
        set quantity_on_hand = quantity_on_hand + %s, updated_at = now()
        where tenant_id = %s and store_id = %s and variant_id = %s
        """,
        (delta, ctx["tenant_id"], ctx["store_id"], variant_id),
    )


def _get_inventory_item(cur, ctx: dict[str, Any], sku_id: str) -> dict[str, Any] | None:
    cur.execute(
        """
        select
            p.id as product_id,
            v.id as variant_id,
            v.sku_id,
            v.barcode,
            v.style_code,
            v.color,
            v.size,
            p.name as product_name,
            p.brand,
            p.category,
            p.gender_target,
            p.season,
            coalesce(b.quantity_on_hand, 0) as current_stock,
            coalesce(v.cost_price_usd, 0) as cost_price_usd,
            coalesce(pr.amount, 0) as retail_price_usd,
            v.reorder_point,
            v.reorder_quantity,
            greatest(p.updated_at, v.updated_at, coalesce(b.updated_at, v.updated_at)) as updated_at
        from core.sku_variants v
        join core.products p on p.id = v.product_id
        left join core.inventory_balances b
            on b.variant_id = v.id and b.store_id = %s
        left join lateral (
            select amount
            from core.prices
            where variant_id = v.id and price_type = 'retail' and valid_to is null
            order by valid_from desc
            limit 1
        ) pr on true
        where v.tenant_id = %s and v.sku_id = %s and v.status = 'active'
        """,
        (ctx["store_id"], ctx["tenant_id"], sku_id),
    )
    row = cur.fetchone()
    return _serialize_item(row) if row else None


def _serialize_item(row: dict[str, Any]) -> dict[str, Any]:
    retail = _number(row.get("retail_price_usd"))
    cost = _number(row.get("cost_price_usd"))
    stock = int(row.get("current_stock") or 0)
    margin = round(((retail - cost) / retail) * 100, 2) if retail else 0
    stock_value = round(cost * stock, 2)
    return {
        **{key: _jsonable(value) for key, value in row.items()},
        "current_stock": stock,
        "retail_price_usd": retail,
        "cost_price_usd": cost,
        "margin_pct": margin,
        "stock_value_usd": stock_value,
        "needs_reorder": stock <= int(row.get("reorder_point") or 0),
    }


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    total_units = sum(int(item["current_stock"]) for item in items)
    inventory_value = sum(float(item["stock_value_usd"]) for item in items)
    retail_value = sum(float(item["retail_price_usd"]) * int(item["current_stock"]) for item in items)
    reorder_count = sum(1 for item in items if item["needs_reorder"])
    categories = sorted({item["category"] for item in items if item.get("category")})
    return {
        "total_skus": len(items),
        "total_units": total_units,
        "inventory_value_at_cost_usd": round(inventory_value, 2),
        "inventory_value_at_retail_usd": round(retail_value, 2),
        "reorder_count": reorder_count,
        "categories": categories,
    }


def _audit(
    cur,
    tenant_id: Any,
    entity_type: str,
    entity_id: str,
    action: str,
    before: Any,
    after: Any,
) -> None:
    cur.execute(
        """
        insert into core.audit_logs (tenant_id, actor, entity_type, entity_id, action, before_state, after_state)
        values (%s, 'frontend', %s, %s, %s, %s::jsonb, %s::jsonb)
        """,
        (
            tenant_id,
            entity_type,
            str(entity_id),
            action,
            json.dumps(_json_dumpable(before)),
            json.dumps(_json_dumpable(after)),
        ),
    )


def _json_dumpable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _json_dumpable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_dumpable(v) for v in value]
    return str(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return round(float(value), 2)


def _safe_database_url() -> str:
    url = database_url()
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    return f"{scheme}://***@{rest.split('@', 1)[1]}"
