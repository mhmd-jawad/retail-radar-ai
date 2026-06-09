from eep.main import _tenant_competitor_market_overview


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchone(self):
        return self.row


def test_tenant_competitor_market_overview_returns_real_counts():
    cur = FakeCursor({
        "competitor_records": 42,
        "shops_covered": 3,
        "data_freshness_hours": 1.234,
    })

    result = _tenant_competitor_market_overview(cur, "tenant-a", skus_tracked=388)

    assert result["status"] == "connected"
    assert result["skus_tracked"] == 388
    assert result["competitor_records"] == 42
    assert result["shops_covered"] == 3
    assert result["data_freshness_hours"] == 1.2
    assert result["avg_price_gap_pct"] is None
    assert cur.params == ("tenant-a",)


def test_tenant_competitor_market_overview_returns_nullable_unavailable_state():
    cur = FakeCursor({
        "competitor_records": 0,
        "shops_covered": 0,
        "data_freshness_hours": None,
    })

    result = _tenant_competitor_market_overview(cur, "tenant-a", skus_tracked=388)

    assert result == {
        "skus_tracked": 388,
        "competitor_records": None,
        "shops_covered": None,
        "avg_price_gap_pct": None,
        "overpriced_skus": None,
        "underpriced_skus": None,
        "at_market_skus": None,
        "data_freshness_hours": None,
        "status": "not_connected",
    }
