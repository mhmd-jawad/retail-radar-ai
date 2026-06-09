from datetime import datetime, timezone

from eep import main


class _FakeCursor:
    def __init__(self, sku_rows, system_decisions):
        self._sku_rows = sku_rows
        self._system_decisions = system_decisions
        self._result = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, _params=()):
        q = query.lower()
        if "from core.sku_variants v" in q:
            self._result = self._sku_rows
        elif "from core.inventory_movements" in q:
            self._result = []
        elif "from core.audit_logs" in q:
            self._result = []
        elif "from marketing.system_decision_latest" in q:
            self._result = self._system_decisions
        elif "from intel.competitor_products_latest" in q:
            self._result = [{"competitor_records": 0, "shops_covered": 0, "data_freshness_hours": None}]
        else:
            raise AssertionError(f"Unexpected query: {query}")

    def fetchone(self):
        return self._result[0] if self._result else {}

    def fetchall(self):
        return self._result


class _FakeConnection:
    def __init__(self, sku_rows, system_decisions):
        self._sku_rows = sku_rows
        self._system_decisions = system_decisions

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return _FakeCursor(self._sku_rows, self._system_decisions)


def test_report_live_promotions_follow_latest_system_decisions(monkeypatch):
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sku_rows = [
        _sku_row("SKU-PROMOTE", "Runner Promote", created_at),
        _sku_row("SKU-MARKDOWN", "Runner Markdown", created_at),
        _sku_row("SKU-HOLD", "Runner Hold", created_at),
    ]
    system_decisions = [
        _decision("SKU-PROMOTE", "PROMOTE", explanation="Latest promote explanation."),
        _decision(
            "SKU-MARKDOWN",
            "MARKDOWN",
            explanation="Latest markdown explanation.",
            suggested_discount_pct=12,
            suggested_price_usd=88,
            margin_after_action_pct=54.5,
        ),
        _decision("SKU-HOLD", "HOLD", explanation="Latest hold explanation."),
    ]

    monkeypatch.setattr(main, "_tenant_id_from_request", lambda _request: "tenant-1")
    monkeypatch.setattr(main, "_context", lambda _cur, tenant_id=None: {"tenant_id": tenant_id, "store_id": "store-1"})
    monkeypatch.setattr(main, "_connect", lambda: _FakeConnection(sku_rows, system_decisions))
    main._clear_read_caches(None)

    report = main.report_live(object())
    promotions = report["promotions"]

    assert promotions["summary"]["promote_count"] == 1
    assert promotions["summary"]["markdown_count"] == 1
    assert promotions["summary"]["hold_count"] == 1
    assert promotions["summary"]["clearance_count"] == 0
    assert promotions["promote"][0]["channels"] == ["Instagram", "Facebook", "In-store window"]
    assert promotions["markdown"][0]["reason"] == "Latest markdown explanation."
    assert promotions["markdown"][0]["suggested_discount_pct"] == 12.0
    assert promotions["markdown"][0]["suggested_price_usd"] == 88.0
    assert promotions["markdown"][0]["margin_after_pct"] == 54.5
    assert promotions["hold_pricing"][0]["reason"] == "Latest hold explanation."


def _sku_row(sku_id: str, product_name: str, created_at: datetime):
    return {
        "variant_id": f"variant-{sku_id}",
        "sku_id": sku_id,
        "product_name": product_name,
        "brand": "Adidas",
        "category": "footwear",
        "cost_price_usd": 40,
        "retail_price_usd": 100,
        "current_stock": 20,
        "variant_created_at": created_at,
    }


def _decision(
    sku_id: str,
    recommendation: str,
    *,
    explanation: str,
    suggested_discount_pct=None,
    suggested_price_usd=None,
    margin_after_action_pct=None,
):
    payload = {
        "recommendation": recommendation,
        "explanation": explanation,
        "suggested_discount_pct": suggested_discount_pct,
        "suggested_price_usd": suggested_price_usd,
        "margin_after_action_pct": margin_after_action_pct,
    }
    return {
        "sku_id": sku_id,
        "status": "live",
        "recommendation": recommendation,
        "confidence": 0.91,
        "suggested_price_usd": suggested_price_usd,
        "suggested_discount_pct": suggested_discount_pct,
        "decision_payload": payload,
        "input_context": {},
        "competitor_signals": {},
        "synced_at": datetime(2026, 6, 9, tzinfo=timezone.utc),
    }
