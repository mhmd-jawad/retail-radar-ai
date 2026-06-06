from contextlib import contextmanager

from eep import retail_db
from eep.retail_db import InventoryImportPayload, InventoryItemPayload


class FakeCursor:
    def __init__(self, records):
        self.records = records
        self.executed = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if "update core.sku_variants" in query and "sku_id <> all" in query:
            tenant_id, seen = params
            seen = set(seen)
            archived = 0
            for (record_tenant, sku_id), record in self.records.items():
                if record_tenant == tenant_id and record.get("status") == "active" and sku_id not in seen:
                    record["status"] = "archived"
                    archived += 1
            self.rowcount = archived


class FakeConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj


def payload(mode, *items):
    return InventoryImportPayload(
        mode=mode,
        items=[
            InventoryItemPayload(
                sku_id=item["sku_id"],
                product_name=item["product_name"],
                brand=item.get("brand", "Brand"),
                category=item.get("category", "Footwear"),
                current_stock=item.get("current_stock", 1),
                retail_price_usd=item.get("retail_price_usd", 100),
                cost_price_usd=item.get("cost_price_usd", 50),
            )
            for item in items
        ],
    )


def install_fake_import_db(monkeypatch):
    records = {}
    cursor = FakeCursor(records)
    audits = []

    @contextmanager
    def fake_connect():
        yield FakeConn(cursor)

    def fake_context(_cur, tenant_id=None, store_code_override=None):
        return {
            "tenant_id": tenant_id,
            "tenant_slug": str(tenant_id),
            "store_id": f"store-{tenant_id}",
            "store_code": store_code_override or "MAIN",
        }

    def fake_upsert(_cur, ctx, item, actor, movement_type):
        key = (ctx["tenant_id"], item.sku_id)
        record = {
            "product_id": f"product-{ctx['tenant_id']}-{item.sku_id}",
            "variant_id": f"variant-{ctx['tenant_id']}-{item.sku_id}",
            "sku_id": item.sku_id,
            "product_name": item.product_name,
            "brand": item.brand,
            "category": item.category,
            "current_stock": item.current_stock,
            "retail_price_usd": item.retail_price_usd,
            "cost_price_usd": item.cost_price_usd,
            "stock_value_usd": item.current_stock * item.cost_price_usd,
            "reorder_point": item.reorder_point,
            "reorder_quantity": item.reorder_quantity,
            "needs_reorder": item.current_stock <= item.reorder_point,
            "status": "active",
            "actor": actor,
            "movement_type": movement_type,
        }
        records[key] = record
        return record

    def fake_audit(_cur, tenant_id, entity_type, entity_id, action, before, after):
        audits.append(
            {
                "tenant_id": tenant_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
                "after": after,
            },
        )

    monkeypatch.setattr(retail_db, "_connect", fake_connect)
    monkeypatch.setattr(retail_db, "_context", fake_context)
    monkeypatch.setattr(retail_db, "_upsert_inventory_item", fake_upsert)
    monkeypatch.setattr(retail_db, "_audit", fake_audit)
    return records, cursor, audits


def test_bulk_import_allows_same_sku_in_different_shops(monkeypatch):
    records, _cursor, audits = install_fake_import_db(monkeypatch)

    shop_a = retail_db.import_inventory(
        payload(
            "upsert",
            {
                "sku_id": "CSV-SHARED-001",
                "product_name": "Shop A Runner",
                "current_stock": 12,
                "retail_price_usd": 120,
                "cost_price_usd": 60,
            },
        ),
        tenant_id="tenant-a",
    )
    shop_b = retail_db.import_inventory(
        payload(
            "upsert",
            {
                "sku_id": "CSV-SHARED-001",
                "product_name": "Shop B Runner",
                "current_stock": 4,
                "retail_price_usd": 95,
                "cost_price_usd": 40,
            },
        ),
        tenant_id="tenant-b",
    )

    assert shop_a["imported"] == 1
    assert shop_b["imported"] == 1
    assert records[("tenant-a", "CSV-SHARED-001")]["product_name"] == "Shop A Runner"
    assert records[("tenant-b", "CSV-SHARED-001")]["product_name"] == "Shop B Runner"
    assert records[("tenant-a", "CSV-SHARED-001")]["current_stock"] == 12
    assert records[("tenant-b", "CSV-SHARED-001")]["current_stock"] == 4
    assert [audit["tenant_id"] for audit in audits] == ["tenant-a", "tenant-b"]


def test_replace_mode_archives_only_current_shop_rows(monkeypatch):
    records, cursor, _audits = install_fake_import_db(monkeypatch)
    records[("tenant-a", "KEEP")] = {"sku_id": "KEEP", "status": "active", "stock_value_usd": 10, "current_stock": 1, "needs_reorder": False, "category": "Footwear", "retail_price_usd": 20}
    records[("tenant-a", "OLD")] = {"sku_id": "OLD", "status": "active", "stock_value_usd": 10, "current_stock": 1, "needs_reorder": False, "category": "Footwear", "retail_price_usd": 20}
    records[("tenant-b", "OLD")] = {"sku_id": "OLD", "status": "active", "stock_value_usd": 10, "current_stock": 1, "needs_reorder": False, "category": "Footwear", "retail_price_usd": 20}

    result = retail_db.import_inventory(
        payload("replace", {"sku_id": "KEEP", "product_name": "Current row"}),
        tenant_id="tenant-a",
    )

    assert result["archived"] == 1
    assert records[("tenant-a", "KEEP")]["status"] == "active"
    assert records[("tenant-a", "OLD")]["status"] == "archived"
    assert records[("tenant-b", "OLD")]["status"] == "active"
    archive_query, archive_params = cursor.executed[-1]
    assert "where tenant_id = %s" in archive_query
    assert archive_params[0] == "tenant-a"
