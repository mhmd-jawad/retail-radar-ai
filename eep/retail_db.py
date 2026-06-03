from __future__ import annotations

import os
import json
import threading
import time
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
_DETAIL_COLUMNS_READY = False
_DETAIL_COLUMNS_LOCK = threading.Lock()


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
    from urllib.parse import urlparse
    _url = urlparse(database_url())
    _host = _url.hostname or "localhost"
    _port = _url.port or 5432
    _tcp_timeout = float(os.environ.get("DATABASE_TCP_TIMEOUT_SECONDS", "10"))
    psycopg, dict_row = _import_psycopg()
    conn = None
    last_connect_error: Exception | None = None
    last_connect_message = f"Cannot connect to PostgreSQL at {_host}:{_port}"
    retries = max(1, int(os.environ.get("DATABASE_CONNECT_RETRIES", "3")))
    retry_delay = float(os.environ.get("DATABASE_CONNECT_RETRY_DELAY_SECONDS", "1"))
    for attempt in range(retries):
        try:
            conn = psycopg.connect(database_url(), row_factory=dict_row, connect_timeout=max(5, int(_tcp_timeout)))
            break
        except Exception as exc:  # pragma: no cover - depends on local DB
            last_connect_error = exc
            last_connect_message = f"Cannot connect to PostgreSQL: {exc}"
        if attempt < retries - 1:
            time.sleep(retry_delay)
    if conn is None:
        raise DatabaseUnavailable(f"{last_connect_message} (attempted {retries} times)") from last_connect_error

    try:
        _ensure_schema(conn)
        _ensure_inventory_detail_columns(conn)
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


def _ensure_inventory_detail_columns(conn) -> None:
    """Apply additive inventory columns on live DBs where full auto-init is disabled."""
    global _DETAIL_COLUMNS_READY
    if _DETAIL_COLUMNS_READY:
        return
    with _DETAIL_COLUMNS_LOCK:
        if _DETAIL_COLUMNS_READY:
            return
        with conn.cursor() as cur:
            cur.execute("select to_regclass('core.sku_variants') as table_name")
            if not cur.fetchone()["table_name"]:
                return
            cur.execute(
                """
                alter table core.sku_variants
                    add column if not exists supplier_id uuid references core.suppliers(id) on delete set null,
                    add column if not exists notes text
                """
            )
            cur.execute(
                """
                create index if not exists idx_sku_variants_supplier
                    on core.sku_variants (tenant_id, supplier_id)
                """
            )
        conn.commit()
        _DETAIL_COLUMNS_READY = True


def _context(cur, tenant_id: Any | None = None, store_code_override: str | None = None) -> dict[str, Any]:
    desired_store = store_code_override or store_code()
    if tenant_id:
        cur.execute(
            """
            select t.id as tenant_id, t.slug as tenant_slug, s.id as store_id, s.code as store_code
            from core.tenants t
            join core.stores s on s.tenant_id = t.id
            where t.id = %s and s.code = %s and s.is_active = true
            """,
            (tenant_id, desired_store),
        )
    else:
        cur.execute(
            """
            select t.id as tenant_id, t.slug as tenant_slug, s.id as store_id, s.code as store_code
            from core.tenants t
            join core.stores s on s.tenant_id = t.id
            where t.slug = %s and s.code = %s and s.is_active = true
            """,
            (tenant_slug(), desired_store),
        )
    row = cur.fetchone()
    if not row:
        raise DatabaseUnavailable(
            f"Tenant/store not found: {tenant_id or tenant_slug()}/{desired_store}. Run the schema first."
        )
    return row


def db_status(tenant_id: Any | None = None) -> dict[str, Any]:
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                ctx = _context(cur, tenant_id=tenant_id)
                cur.execute("select count(*) as item_count from core.sku_variants where tenant_id = %s", (ctx["tenant_id"],))
                count = cur.fetchone()["item_count"]
        return {
            "connected": True,
            "database_url_hint": _safe_database_url(),
            "tenant": ctx["tenant_slug"],
            "store": ctx["store_code"],
            "item_count": int(count),
            "schema_auto_init": os.environ.get("RETAIL_AUTO_INIT_DB", "true"),
        }
    except Exception as exc:
        return {
            "connected": False,
            "database_url_hint": _safe_database_url(),
            "tenant": str(tenant_id) if tenant_id else tenant_slug(),
            "store": store_code(),
            "error": str(exc),
        }


def list_inventory_items(search: str | None = None, limit: int = 500, tenant_id: Any | None = None) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
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
                    " or lower(coalesce(p.gender_target, '')) like %s"
                    " or lower(coalesce(p.season, '')) like %s"
                    " or lower(coalesce(v.color, '')) like %s"
                    " or lower(coalesce(v.size, '')) like %s"
                    " or lower(coalesce(sup.name, '')) like %s"
                    ")"
                )
                params.extend([search_param] * 9)
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
                    v.notes,
                    p.name as product_name,
                    p.brand,
                    p.category,
                    p.gender_target,
                    p.season,
                    sup.name as supplier_name,
                    coalesce(b.quantity_on_hand, 0) as current_stock,
                    coalesce(v.cost_price_usd, 0) as cost_price_usd,
                    coalesce(pr.amount, 0) as retail_price_usd,
                    v.reorder_point,
                    v.reorder_quantity,
                    greatest(p.updated_at, v.updated_at, coalesce(b.updated_at, v.updated_at)) as updated_at
                from core.sku_variants v
                join core.products p on p.id = v.product_id
                left join core.suppliers sup on sup.id = v.supplier_id
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


def create_inventory_item(payload: InventoryItemPayload, tenant_id: Any | None = None) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            item = _upsert_inventory_item(cur, ctx, payload, actor="frontend", movement_type="initial_stock")
            item_with_context = _attach_payload_context(item, payload)
            _audit(cur, ctx["tenant_id"], "inventory_item", item["sku_id"], "upsert", None, item_with_context)
    return item_with_context


def update_inventory_item(sku_id: str, payload: InventoryItemPayload, tenant_id: Any | None = None) -> dict[str, Any]:
    data = payload.model_copy(update={"sku_id": sku_id})
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            before = _get_inventory_item(cur, ctx, sku_id)
            if not before:
                raise KeyError(sku_id)
            item = _upsert_inventory_item(cur, ctx, data, actor="frontend", movement_type="adjustment_in")
            item_with_context = _attach_payload_context(item, data)
            _audit(cur, ctx["tenant_id"], "inventory_item", item["sku_id"], "update", before, item_with_context)
    return item_with_context


def patch_inventory_price(
    sku_id: str,
    new_price: float,
    decision_type: str,
    notes: str | None = None,
    tenant_id: Any | None = None,
) -> dict[str, Any]:
    """Patch only the retail_price_usd for a SKU and write an audit entry."""
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            before = _get_inventory_item(cur, ctx, sku_id)
            if not before:
                raise KeyError(sku_id)
            variant_id = before["variant_id"]
            _set_current_price(cur, ctx["tenant_id"], variant_id, new_price)
            after = _get_inventory_item(cur, ctx, sku_id)
            if not after:
                raise RuntimeError(f"Failed to reload SKU {sku_id} after price patch")
            actor = f"retailer_decision_{decision_type}"
            detail: dict[str, Any] = {"decision_type": decision_type, "new_price_usd": new_price}
            if notes:
                detail["notes"] = notes
            _audit(cur, ctx["tenant_id"], "inventory_item", sku_id, actor, before, {**after, **detail})
    return after


def record_retailer_decision(
    sku_id: str,
    decision_type: str,
    notes: str | None = None,
    tenant_id: Any | None = None,
) -> dict[str, Any]:
    """Record a non-price retailer decision (e.g. hold acknowledgement) in the audit log."""
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            item = _get_inventory_item(cur, ctx, sku_id)
            if not item:
                raise KeyError(sku_id)
            detail: dict[str, Any] = {"decision_type": decision_type}
            if notes:
                detail["notes"] = notes
            _audit(cur, ctx["tenant_id"], "inventory_item", sku_id, f"retailer_decision_{decision_type}", None, detail)
    return {"ok": True, "sku_id": sku_id, "decision_type": decision_type}


def archive_inventory_item(sku_id: str, tenant_id: Any | None = None) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
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


def import_inventory(payload: InventoryImportPayload, tenant_id: Any | None = None) -> dict[str, Any]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            for entry in payload.items:
                item = _upsert_inventory_item(
                    cur,
                    ctx,
                    entry,
                    actor="bulk_import",
                    movement_type="full_import_adjustment",
                )
                item_with_context = _attach_payload_context(item, entry)
                seen.add(item_with_context["sku_id"])
                items.append(item_with_context)

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
    supplier_id = _upsert_supplier(cur, ctx["tenant_id"], data.get("supplier_name"))
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
                reorder_point = %s, reorder_quantity = %s, supplier_id = %s, notes = %s,
                status = 'active', updated_at = now()
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
                supplier_id,
                data["notes"],
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
                cost_price_usd, reorder_point, reorder_quantity, supplier_id, notes
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                supplier_id,
                data["notes"],
            ),
        )
        variant_id = cur.fetchone()["id"]

    _set_current_price(cur, ctx["tenant_id"], variant_id, data["retail_price_usd"])
    _set_current_stock(
        cur,
        ctx,
        variant_id,
        data["current_stock"],
        data["cost_price_usd"],
        actor,
        movement_type,
        data.get("notes"),
    )
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
    notes: str | None = None,
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
        values (%s, %s, %s, %s, %s, %s, 'inventory_ui', %s, %s)
        """,
        (
            ctx["tenant_id"],
            ctx["store_id"],
            variant_id,
            movement,
            delta,
            unit_cost,
            notes or "Set current stock from frontend",
            actor,
        ),
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
            v.notes,
            p.name as product_name,
            p.brand,
            p.category,
            p.gender_target,
            p.season,
            sup.name as supplier_name,
            coalesce(b.quantity_on_hand, 0) as current_stock,
            coalesce(v.cost_price_usd, 0) as cost_price_usd,
            coalesce(pr.amount, 0) as retail_price_usd,
            v.reorder_point,
            v.reorder_quantity,
            greatest(p.updated_at, v.updated_at, coalesce(b.updated_at, v.updated_at)) as updated_at
        from core.sku_variants v
        join core.products p on p.id = v.product_id
        left join core.suppliers sup on sup.id = v.supplier_id
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


def _upsert_supplier(cur, tenant_id: Any, supplier_name: str | None) -> Any | None:
    if not supplier_name:
        return None
    cur.execute(
        """
        insert into core.suppliers (tenant_id, name, is_active)
        values (%s, %s, true)
        on conflict (tenant_id, name) do update set
            is_active = true,
            updated_at = now()
        returning id
        """,
        (tenant_id, supplier_name),
    )
    return cur.fetchone()["id"]


def _attach_payload_context(item: dict[str, Any], payload: InventoryItemPayload) -> dict[str, Any]:
    data = payload.model_dump()
    context = {
        key: data.get(key)
        for key in ("supplier_name", "notes")
        if data.get(key) is not None
    }
    return {**item, **context}


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


# ─── Outcome Tracking DB helpers ─────────────────────────────────────────────

def get_variant_id_for_sku(sku_id: str) -> str | None:
    """Return the UUID variant_id for a given sku_id string."""
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            cur.execute(
                "select id from core.sku_variants where tenant_id = %s and sku_id = %s and status = 'active'",
                (ctx["tenant_id"], sku_id),
            )
            row = cur.fetchone()
            return str(row["id"]) if row else None


def get_tenant_id() -> str:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            return str(ctx["tenant_id"])


def query_velocity_window(
    variant_id: str,
    window_start: "datetime",
    window_end: "datetime",
) -> dict[str, Any]:
    """
    Compute real velocity metrics from sales_transactions + sales_transaction_lines
    for a specific variant_id over [window_start, window_end).

    Returns dict with keys:
        total_units, total_revenue, avg_unit_price, velocity_daily, data_available
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(stl.quantity), 0)              AS total_units,
                    COALESCE(SUM(stl.quantity * stl.unit_price_usd), 0) AS total_revenue,
                    CASE WHEN SUM(stl.quantity) > 0
                         THEN SUM(stl.quantity * stl.unit_price_usd) / SUM(stl.quantity)
                         ELSE 0 END                             AS avg_unit_price
                FROM core.sales_transactions st
                JOIN core.sales_transaction_lines stl ON st.id = stl.sales_transaction_id
                WHERE stl.variant_id = %s
                  AND st.tenant_id = %s
                  AND st.sold_at >= %s
                  AND st.sold_at < %s
                """,
                (variant_id, ctx["tenant_id"], window_start, window_end),
            )
            row = cur.fetchone()

    total_units = int(row["total_units"] or 0)
    total_revenue = _number(row["total_revenue"])
    avg_price = _number(row["avg_unit_price"])
    window_days = max((window_end - window_start).days, 1)
    velocity_daily = round(total_units / window_days, 4)

    return {
        "total_units": total_units,
        "total_revenue": total_revenue,
        "avg_unit_price": avg_price,
        "velocity_daily": velocity_daily,
        "window_days": window_days,
        "data_available": total_units > 0,
    }


def query_daily_sales_series(
    variant_id: str,
    series_start: "datetime",
    series_end: "datetime",
) -> list[dict[str, Any]]:
    """
    Return day-by-day units sold and revenue for a variant.
    Used for the velocity timeline chart in OutcomePanel.
    Returns list of { date: str, units_sold: int, revenue: float }.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            cur.execute(
                """
                SELECT
                    DATE(st.sold_at)                            AS sale_date,
                    COALESCE(SUM(stl.quantity), 0)              AS units_sold,
                    COALESCE(SUM(stl.quantity * stl.unit_price_usd), 0) AS revenue
                FROM core.sales_transactions st
                JOIN core.sales_transaction_lines stl ON st.id = stl.sales_transaction_id
                WHERE stl.variant_id = %s
                  AND st.tenant_id = %s
                  AND st.sold_at >= %s
                  AND st.sold_at < %s
                GROUP BY DATE(st.sold_at)
                ORDER BY sale_date
                """,
                (variant_id, ctx["tenant_id"], series_start, series_end),
            )
            rows = cur.fetchall() or []

    return [
        {
            "date": row["sale_date"].isoformat(),
            "units_sold": int(row["units_sold"] or 0),
            "revenue": _number(row["revenue"]),
        }
        for row in rows
    ]


def get_current_stock_for_variant(variant_id: str) -> int:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            cur.execute(
                """
                SELECT COALESCE(quantity_on_hand, 0) AS qty
                FROM core.inventory_balances
                WHERE tenant_id = %s AND store_id = %s AND variant_id = %s
                """,
                (ctx["tenant_id"], ctx["store_id"], variant_id),
            )
            row = cur.fetchone()
            return int(row["qty"]) if row else 0


def get_recommendation_by_id(recommendation_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            cur.execute(
                """
                SELECT id, recommendation, confidence, explanation,
                       suggested_discount_pct, suggested_price_usd, status
                FROM marketing.recommendations
                WHERE tenant_id = %s AND id = %s
                """,
                (ctx["tenant_id"], recommendation_id),
            )
            row = cur.fetchone()
            return {k: _jsonable(v) for k, v in row.items()} if row else None


def insert_decision_snapshot(data: dict[str, Any]) -> int:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            cur.execute(
                """
                INSERT INTO outcome_tracking.decision_snapshots (
                    tenant_id, variant_id, recommendation_id, decision_type, approved_at,
                    baseline_velocity_daily, baseline_revenue_7d, baseline_avg_price,
                    baseline_qty_on_hand, baseline_margin_pct, baseline_dos,
                    predicted_lift_pct, ie2_confidence, ie2_explanation, suggested_discount_pct,
                    check_7d_at, check_14d_at, status
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s
                )
                RETURNING id
                """,
                (
                    ctx["tenant_id"],
                    data["variant_id"],
                    data.get("recommendation_id"),
                    data["decision_type"],
                    data["approved_at"],
                    data.get("baseline_velocity_daily"),
                    data.get("baseline_revenue_7d"),
                    data.get("baseline_avg_price"),
                    data.get("baseline_qty_on_hand"),
                    data.get("baseline_margin_pct"),
                    data.get("baseline_dos"),
                    data.get("predicted_lift_pct"),
                    data.get("ie2_confidence"),
                    data.get("ie2_explanation"),
                    data.get("suggested_discount_pct"),
                    data.get("check_7d_at"),
                    data.get("check_14d_at"),
                    data.get("status", "tracking"),
                ),
            )
            snapshot_id = cur.fetchone()["id"]
    return snapshot_id


def get_snapshot_by_id(snapshot_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM outcome_tracking.decision_snapshots WHERE id = %s",
                (snapshot_id,),
            )
            row = cur.fetchone()
            return {k: _jsonable(v) for k, v in row.items()} if row else None


def get_snapshots_for_variant(variant_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            cur.execute(
                """
                SELECT s.*, json_agg(
                    json_build_object(
                        'id', m.id,
                        'window_days', m.window_days,
                        'measured_at', m.measured_at,
                        'actual_velocity_daily', m.actual_velocity_daily,
                        'actual_revenue_total', m.actual_revenue_total,
                        'actual_qty_sold', m.actual_qty_sold,
                        'actual_avg_price', m.actual_avg_price,
                        'velocity_lift_pct', m.velocity_lift_pct,
                        'revenue_delta_usd', m.revenue_delta_usd,
                        'campaign_roi_usd', m.campaign_roi_usd,
                        'accuracy_score', m.accuracy_score,
                        'narrative', m.narrative,
                        'data_available', m.data_available
                    ) ORDER BY m.window_days
                ) FILTER (WHERE m.id IS NOT NULL) AS measurements
                FROM outcome_tracking.decision_snapshots s
                LEFT JOIN outcome_tracking.outcome_measurements m ON m.snapshot_id = s.id
                WHERE s.tenant_id = %s AND s.variant_id = %s
                GROUP BY s.id
                ORDER BY s.approved_at DESC
                """,
                (ctx["tenant_id"], variant_id),
            )
            rows = cur.fetchall() or []
            return [{k: _jsonable(v) for k, v in row.items()} for row in rows]


def insert_outcome_measurement(data: dict[str, Any]) -> int:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO outcome_tracking.outcome_measurements (
                    snapshot_id, window_days,
                    actual_velocity_daily, actual_revenue_total, actual_qty_sold, actual_avg_price,
                    velocity_lift_pct, revenue_delta_usd, campaign_roi_usd, accuracy_score,
                    narrative, llm_computed_lift_pct, llm_computed_revenue_delta, data_available
                ) VALUES (
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                ON CONFLICT (snapshot_id, window_days) DO UPDATE SET
                    actual_velocity_daily = EXCLUDED.actual_velocity_daily,
                    actual_revenue_total = EXCLUDED.actual_revenue_total,
                    actual_qty_sold = EXCLUDED.actual_qty_sold,
                    actual_avg_price = EXCLUDED.actual_avg_price,
                    velocity_lift_pct = EXCLUDED.velocity_lift_pct,
                    revenue_delta_usd = EXCLUDED.revenue_delta_usd,
                    campaign_roi_usd = EXCLUDED.campaign_roi_usd,
                    accuracy_score = EXCLUDED.accuracy_score,
                    narrative = EXCLUDED.narrative,
                    llm_computed_lift_pct = EXCLUDED.llm_computed_lift_pct,
                    llm_computed_revenue_delta = EXCLUDED.llm_computed_revenue_delta,
                    data_available = EXCLUDED.data_available,
                    measured_at = now()
                RETURNING id
                """,
                (
                    data["snapshot_id"],
                    data["window_days"],
                    data.get("actual_velocity_daily"),
                    data.get("actual_revenue_total"),
                    data.get("actual_qty_sold"),
                    data.get("actual_avg_price"),
                    data.get("velocity_lift_pct"),
                    data.get("revenue_delta_usd"),
                    data.get("campaign_roi_usd"),
                    data.get("accuracy_score"),
                    data.get("narrative"),
                    data.get("llm_computed_lift_pct"),
                    data.get("llm_computed_revenue_delta"),
                    data.get("data_available", True),
                ),
            )
            return cur.fetchone()["id"]


def update_snapshot_status(snapshot_id: int, status: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE outcome_tracking.decision_snapshots SET status = %s WHERE id = %s",
                (status, snapshot_id),
            )


def get_portfolio_accuracy(decision_type: str | None = None) -> dict[str, Any]:
    """Aggregate accuracy scores across all completed measurements."""
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur)
            if decision_type:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS decision_count,
                        AVG(m.accuracy_score) AS avg_accuracy,
                        s.decision_type
                    FROM outcome_tracking.outcome_measurements m
                    JOIN outcome_tracking.decision_snapshots s ON s.id = m.snapshot_id
                    WHERE s.tenant_id = %s AND m.data_available = true
                      AND s.decision_type = %s AND m.window_days = 7
                    GROUP BY s.decision_type
                    """,
                    (ctx["tenant_id"], decision_type),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS decision_count,
                        AVG(m.accuracy_score) AS avg_accuracy,
                        s.decision_type
                    FROM outcome_tracking.outcome_measurements m
                    JOIN outcome_tracking.decision_snapshots s ON s.id = m.snapshot_id
                    WHERE s.tenant_id = %s AND m.data_available = true AND m.window_days = 7
                    GROUP BY s.decision_type
                    """,
                    (ctx["tenant_id"],),
                )
            rows = cur.fetchall() or []

    by_type: dict[str, float] = {}
    total_count = 0
    total_acc_sum = 0.0
    for row in rows:
        dt = row["decision_type"]
        acc = float(row["avg_accuracy"] or 0)
        cnt = int(row["decision_count"] or 0)
        by_type[dt] = round(acc * 100, 1)
        total_count += cnt
        total_acc_sum += acc * cnt

    avg_acc = round((total_acc_sum / total_count) * 100, 1) if total_count > 0 else None
    return {
        "avg_accuracy": avg_acc,
        "decision_count": total_count,
        "by_type": by_type,
    }
