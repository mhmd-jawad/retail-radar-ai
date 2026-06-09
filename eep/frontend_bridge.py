"""
Data assembly bridge between raw storage and the frontend API.

Reads from the StylePulse report JSON, live product/inventory CSVs,
competitor price data, and PostgreSQL, then assembles dashboard-ready
response payloads for the EEP frontend endpoints.

Key responsibilities:

- Transform StylePulse analysis results into per-SKU dashboard cards
- Build competitor price comparison tables
- Construct inventory health summaries with trend data

"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any

from services.market_intelligence.competitor_processor import build_competitor_signals_for_product
from services.common.price_normalization import (
    effective_competitor_price_usd,
    normalize_competitor_price_usd,
    price_gap_pct,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "data" / "reports" / "report.json"
PRODUCTS_PATH = ROOT / "data" / "real" / "products.csv"
INVENTORY_PATH = ROOT / "data" / "real" / "inventory.csv"
HISTORICAL_STATES_PATH = ROOT / "data" / "features" / "historical_product_states.csv"
SCRAPING_OUTPUT_ROOT = ROOT / "scraping" / "data" / "output"
SCRAPE_MANIFEST_PATH = SCRAPING_OUTPUT_ROOT / "manifest.json"
DEFAULT_REPORT_WINDOW_DAYS = 90

_TS_TOKEN = re.compile(r"(?P<stamp>\d{8}T\d{6}Z)")


def _read_intel_rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]] | None:
    """Use RDS/local PostgreSQL when configured; retain file data for offline use."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return None
    try:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return list(cur.fetchall())
    except Exception as exc:
        raise RuntimeError("Cannot read scraper intelligence tables from configured PostgreSQL.") from exc


def _as_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or _iso_now())

CATEGORY_LABELS = {
    "footwear": "Footwear",
    "football_boots": "Football Boots",
    "apparel": "Apparel",
    "sportswear": "Sportswear",
    "swimwear": "Swimwear",
    "accessories": "Accessories",
    "kids": "Kids",
    "lifestyle": "Lifestyle",
    "other": "Other",
}

SERVICE_OWNERS = {
    "inventory": "Operations",
    "marketing": "Marketing",
    "planning": "Operations",
    "pricing": "Buying",
    "supply_chain": "Operations",
}

ALERT_TITLES = {
    "dead_stock": "Dead stock requires action",
    "stockout_risk": "Reorder risk detected",
    "slow_mover": "Slow-moving stock pressure",
    "margin_warning": "Margin floor warning",
    "inventory_concentration": "Inventory concentration risk",
}

PRIORITY_URGENCY = {
    "immediate": "critical",
    "this_week": "high",
    "this_month": "medium",
    "ongoing": "low",
}

SEASONAL_ACTIONS = {
    "peak_demand": ("PROMOTE", "Core Assortment"),
    "slow_period": ("MARKDOWN", "Aging Inventory"),
    "event": ("PROMOTE", "Seasonal Event"),
    "normal": ("HOLD", "Market"),
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts if part is not None)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _friendly_category(value: Any) -> str:
    key = str(value or "other").strip().lower().replace(" ", "_")
    return CATEGORY_LABELS.get(key, key.replace("_", " ").title())


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _timestamp_from_token(value: str | None) -> datetime | None:
    if not value:
        return None
    match = _TS_TOKEN.search(value)
    if not match:
        return None
    return datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _file_iso_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def load_raw_report() -> dict[str, Any]:
    if REPORT_PATH.exists():
        return _read_json(REPORT_PATH)

    from stylepulse.engine import run

    return run()


@lru_cache(maxsize=1)
def load_products_index() -> dict[str, dict[str, str]]:
    if not PRODUCTS_PATH.exists():
        return {}
    return {row["sku_id"]: row for row in _read_csv(PRODUCTS_PATH)}


@lru_cache(maxsize=1)
def load_inventory_index() -> dict[str, dict[str, str]]:
    if not INVENTORY_PATH.exists():
        return {}
    return {row["sku_id"]: row for row in _read_csv(INVENTORY_PATH)}


@lru_cache(maxsize=1)


@lru_cache(maxsize=1)


@lru_cache(maxsize=1)
def load_latest_state_index() -> dict[str, dict[str, str]]:
    if not HISTORICAL_STATES_PATH.exists():
        return {}

    latest: dict[str, dict[str, str]] = {}
    for row in _read_csv(HISTORICAL_STATES_PATH):
        sku_id = row.get("sku_id")
        week_of = row.get("week_of", "")
        if not sku_id:
            continue
        current = latest.get(sku_id)
        if current is None or week_of > current.get("week_of", ""):
            latest[sku_id] = row
    return latest


@lru_cache(maxsize=1)
def load_scrape_manifest() -> dict[str, Any]:
    if not SCRAPE_MANIFEST_PATH.exists():
        return {"shops": {}}
    return _read_json(SCRAPE_MANIFEST_PATH)


def report_generated_at() -> str:
    raw_report = load_raw_report()
    metadata = raw_report.get("metadata", {})
    candidate = metadata.get("generated_at")
    parsed = _parse_iso(candidate)
    if parsed is not None:
        return parsed.astimezone(timezone.utc).isoformat()
    if REPORT_PATH.exists():
        return _file_iso_timestamp(REPORT_PATH)
    return _iso_now()


def report_overview() -> dict[str, int]:
    manifest = load_scrape_manifest()
    raw_report = load_raw_report()
    return {
        "sku_count": len(raw_report.get("inventory", {}).get("sku_analysis", [])),
        "shop_count": len(manifest.get("shops", {})),
    }


def _build_decision_lookup(raw_report: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    promotions = raw_report.get("promotions", {})
    for sku in promotions.get("hold_pricing", []):
        lookup[sku["sku_id"]] = "HOLD"
    for sku in promotions.get("promote", []):
        lookup[sku["sku_id"]] = "PROMOTE"
    for sku in promotions.get("markdown", []):
        lookup[sku["sku_id"]] = "MARKDOWN"
    for sku in promotions.get("clearance", []):
        lookup[sku["sku_id"]] = "CLEAR"
    return lookup


def _median_days(items: list[dict[str, Any]]) -> float:
    if not items:
        return 0.0
    return round(float(median(item["days_of_supply"] for item in items)), 1)


def _category_health_score(median_dos: float, avg_margin_pct: float) -> int:
    score = 100 - abs(median_dos - 60) * 0.6 - max(0, 45 - avg_margin_pct) * 1.5
    return int(round(max(0, min(100, score))))


def _inventory_alerts(raw_alerts: list[dict[str, Any]], sku_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    created_at = report_generated_at()
    alerts: list[dict[str, Any]] = []
    for alert in raw_alerts:
        sku_id = alert.get("sku_id")
        sku = sku_map.get(sku_id or "", {})
        alert_type = str(alert.get("type", "alert"))
        severity = str(alert.get("severity", "low")).lower()
        title = ALERT_TITLES.get(alert_type, alert_type.replace("_", " ").title())
        product_name = sku.get("product_name") or alert.get("product_name")
        if product_name and alert_type in {"dead_stock", "stockout_risk"}:
            title = f"{title}: {product_name}"
        alerts.append(
            {
                "id": _stable_id("inv", alert_type, sku_id or product_name or title),
                "severity": "critical" if alert_type == "dead_stock" else severity,
                "title": title,
                "detail": alert.get("message", title),
                "category": sku.get("category"),
                "sku_id": sku_id,
                "created_at": created_at,
            }
        )
    return alerts




def build_frontend_report() -> dict[str, Any]:
    raw_report = load_raw_report()
    products = load_products_index()
    inventory_rows = load_inventory_index()
    latest_states = load_latest_state_index()
    decision_lookup = _build_decision_lookup(raw_report)

    inventory_skus: list[dict[str, Any]] = []
    inventory_sku_map: dict[str, dict[str, Any]] = {}

    for raw_sku in raw_report.get("inventory", {}).get("sku_analysis", []):
        sku_id = raw_sku["sku_id"]
        product = products.get(sku_id, {})
        inventory_row = inventory_rows.get(sku_id, {})
        state = latest_states.get(sku_id, {})

        category = _friendly_category(
            state.get("category")
            or raw_sku.get("system_category")
            or product.get("system_category")
        )
        current_stock = _to_int(raw_sku.get("current_stock"), _to_int(inventory_row.get("current_stock"), 0))
        initial_stock = _to_int(
            state.get("inventory_initial_stock"),
            _to_int(product.get("initial_stock"), _to_int(inventory_row.get("initial_stock"), current_stock)),
        )
        velocity = round(
            _to_float(raw_sku.get("estimated_daily_demand"), 0.0)
            or _to_float(state.get("sell_through_proxy"), 0.0),
            2,
        )
        health = {
            "critical": "critical",
            "healthy": "healthy",
            "excess": "excess",
            "dead": "dead",
        }.get(str(raw_sku.get("dos_status", "healthy")).lower(), "healthy")

        transformed = {
            "sku_id": sku_id,
            "product_name": raw_sku.get("product_name") or product.get("product_name") or inventory_row.get("product_name"),
            "brand": raw_sku.get("brand") or product.get("brand") or inventory_row.get("brand") or "Unknown",
            "category": category,
            "current_stock": current_stock,
            "initial_stock": initial_stock,
            "retail_price_usd": round(_to_float(raw_sku.get("retail_price_usd"), _to_float(product.get("retail_price_usd"), 0.0)), 2),
            "cost_price_usd": round(_to_float(raw_sku.get("cost_price_usd"), _to_float(product.get("cost_price_usd"), 0.0)), 2),
            "margin_pct": round(_to_float(raw_sku.get("margin_pct"), 0.0), 1),
            "days_of_supply": round(_to_float(raw_sku.get("days_of_supply"), 0.0), 1),
            "days_since_launch": _to_int(state.get("days_since_launch"), 180),
            "days_since_last_discount": _to_int(state.get("days_since_last_discount"), 999),
            "days_at_current_price": _to_int(state.get("days_at_current_price"), 30),
            "velocity_units_per_day": velocity,
            "health": health,
            "decision": decision_lookup.get(sku_id, "HOLD"),
        }
        inventory_skus.append(transformed)
        inventory_sku_map[sku_id] = transformed

    inventory_metrics_raw = raw_report.get("inventory", {}).get("metrics", {})
    category_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sku in inventory_skus:
        category_buckets[sku["category"]].append(sku)

    inventory_category_summary: dict[str, Any] = {}
    for category, items in sorted(category_buckets.items()):
        avg_margin = round(sum(item["margin_pct"] for item in items) / len(items), 1) if items else 0.0
        med_dos = _median_days(items)
        value_usd = round(sum(item["current_stock"] * item["cost_price_usd"] for item in items), 2)
        inventory_category_summary[category] = {
            "skus": len(items),
            "units": sum(item["current_stock"] for item in items),
            "value_usd": value_usd,
            "avg_margin_pct": avg_margin,
            "median_dos": med_dos,
            "health_score": _category_health_score(med_dos, avg_margin),
        }

    competitor_positions: list[dict[str, Any]] = []
    for raw_position in raw_report.get("competitor", {}).get("sku_positioning", []):
        sku_id = raw_position["sku_id"]
        product = products.get(sku_id, {})
        state = latest_states.get(sku_id, {})
        competitor_names = [name.strip() for name in str(product.get("competitors", "")).split(",") if name.strip()]

        our_price = _to_float(raw_position.get("our_price_usd"), _to_float(product.get("retail_price_usd"), 0.0))
        market_min = normalize_competitor_price_usd(
            raw_position.get("market_min_usd"),
            raw_position.get("currency"),
        ) or normalize_competitor_price_usd(product.get("market_min_price_usd"))
        market_avg = normalize_competitor_price_usd(
            state.get("competitor_avg_price_usd"),
            state.get("currency"),
        ) or normalize_competitor_price_usd(
            raw_position.get("market_median_usd"),
            raw_position.get("currency"),
        ) or normalize_competitor_price_usd(product.get("market_median_price_usd"))
        gap = price_gap_pct(our_price, market_min) if market_min else None

        competitor_positions.append(
            {
                "sku_id": sku_id,
                "product_name": raw_position.get("product_name") or product.get("product_name"),
                "brand": raw_position.get("brand") or product.get("brand") or "Unknown",
                "category": _friendly_category(raw_position.get("system_category") or product.get("system_category")),
                "our_price_usd": round(our_price, 2),
                "market_min_usd": round(market_min or 0.0, 2),
                "market_avg_usd": round(market_avg or market_min or 0.0, 2),
                "price_gap_pct": gap if gap is not None else round(_to_float(raw_position.get("price_gap_pct"), 0.0), 1),
                "position": raw_position.get("position", "at_market"),
                "competitors_count": _to_int(raw_position.get("num_competitors"), _to_int(product.get("num_competitors"), 0)),
                "competitors_on_sale": _to_int(raw_position.get("competitors_on_sale"), _to_int(state.get("competitors_on_sale_count"), 0)),
                "cheapest_shop": competitor_names[0] if competitor_names else "market",
            }
        )

    positions_by_sku = {item["sku_id"]: item for item in competitor_positions}
    competitor_market_overview_raw = raw_report.get("competitor", {}).get("market_overview", {})
    latest_freshness_values = [
        _to_float(state.get("data_freshness_hours"), 0.0)
        for state in latest_states.values()
        if state.get("data_freshness_hours") not in (None, "")
    ]
    competitor_freshness = round(float(median(latest_freshness_values)), 1) if latest_freshness_values else 0.0

    brand_summary: dict[str, Any] = {}
    brands: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for position in competitor_positions:
        brands[position["brand"]].append(position)
    for brand, items in brands.items():
        avg_gap = round(sum(item["price_gap_pct"] for item in items) / len(items), 1)
        if avg_gap > 15:
            position_label = "premium"
        elif avg_gap > 5:
            position_label = "above_market"
        elif avg_gap > -5:
            position_label = "at_market"
        elif avg_gap > -15:
            position_label = "below_market"
        else:
            position_label = "deep_value"
        brand_summary[brand] = {
            "skus": len(items),
            "avg_gap_pct": avg_gap,
            "position": position_label,
            "coverage": round(len(items) / max(len(competitor_positions), 1), 2),
        }

    competitor_category_summary: dict[str, Any] = {}
    competitor_categories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for position in competitor_positions:
        competitor_categories[position["category"]].append(position)
    for category, items in competitor_categories.items():
        competitor_category_summary[category] = {
            "skus": len(items),
            "avg_gap_pct": round(sum(item["price_gap_pct"] for item in items) / len(items), 1),
        }

    opportunities: list[dict[str, Any]] = []
    candidate_positions = [
        item for item in competitor_positions
        if item["price_gap_pct"] > 15 or item["price_gap_pct"] < -10
    ]
    for position in sorted(candidate_positions, key=lambda item: abs(item["price_gap_pct"]), reverse=True)[:12]:
        sku = inventory_sku_map.get(position["sku_id"], {})
        current_price = position["our_price_usd"]
        market_avg = position["market_avg_usd"]
        velocity = max(_to_float(sku.get("velocity_units_per_day"), 0.0), 0.5)
        if position["price_gap_pct"] > 0:
            type_ = "undercut"
            suggested_price = round(market_avg * 0.98, 2)
            rationale = (
                f"Priced {position['price_gap_pct']:.1f}% above market. "
                f"Closing toward {position['cheapest_shop']} should recover demand."
            )
        else:
            type_ = "raise"
            suggested_price = round(market_avg * 1.03, 2)
            rationale = (
                f"Priced {abs(position['price_gap_pct']):.1f}% below market. "
                "There is room to recover margin without losing competitiveness."
            )
        opportunities.append(
            {
                "sku_id": position["sku_id"],
                "product_name": position["product_name"],
                "brand": position["brand"],
                "type": type_,
                "current_price_usd": current_price,
                "suggested_price_usd": suggested_price,
                "est_uplift_usd": round(abs(suggested_price - current_price) * velocity * 30, 2),
                "rationale": rationale,
            }
        )


    promotions_raw = raw_report.get("promotions", {})
    promote_items = []
    for item in promotions_raw.get("promote", []):
        sku = inventory_sku_map.get(item["sku_id"], {})
        seasonal_multiplier = _to_float(item.get("seasonal_multiplier"), 1.0)
        expected_lift = round(max(seasonal_multiplier - 1.0, 0.0) * 100 + max(_to_float(item.get("current_margin_pct"), 0.0) - 35.0, 0.0) / 5, 1)
        promote_items.append(
            {
                "sku_id": item["sku_id"],
                "product_name": item.get("product_name") or sku.get("product_name"),
                "brand": item.get("brand") or sku.get("brand") or "Unknown",
                "category": _friendly_category(item.get("category") or sku.get("category")),
                "reason": item.get("reason", ""),
                "expected_lift_pct": expected_lift,
                "channels": ["Instagram", "Facebook", "In-store window"],
            }
        )

    markdown_items = []
    for item in promotions_raw.get("markdown", []):
        sku = inventory_sku_map.get(item["sku_id"], {})
        margin_after = round(_to_float(item.get("post_markdown_margin_pct"), 0.0), 1)
        priority = str(item.get("priority", "this_month"))
        markdown_items.append(
            {
                "sku_id": item["sku_id"],
                "product_name": item.get("product_name") or sku.get("product_name"),
                "brand": item.get("brand") or sku.get("brand") or "Unknown",
                "current_price_usd": round(_to_float(sku.get("retail_price_usd"), 0.0), 2),
                "suggested_discount_pct": round(_to_float(item.get("recommended_discount_pct"), 0.0), 0),
                "suggested_price_usd": round(_to_float(sku.get("retail_price_usd"), 0.0) * (1 - _to_float(item.get("recommended_discount_pct"), 0.0) / 100), 2),
                "margin_after_pct": margin_after,
                "reason": item.get("reason", ""),
                "urgency": (
                    "high" if priority in {"immediate", "this_week"} or margin_after < 35
                    else "medium" if priority == "this_month"
                    else "low"
                ),
            }
        )

    clearance_items = []
    for item in promotions_raw.get("clearance", []):
        sku = inventory_sku_map.get(item["sku_id"], {})
        current_price = _to_float(sku.get("retail_price_usd"), 0.0)
        discount_pct = _to_float(item.get("recommended_discount_pct"), 50.0)
        suggested_price = round(current_price * (1 - discount_pct / 100), 2) if current_price > 0 else round(_to_float(item.get("value_at_cost_usd"), 0.0) / max(_to_int(item.get("current_stock"), 1), 1) * 0.5, 2)
        recovered_cash = round(suggested_price * max(_to_int(item.get("current_stock"), 0), 1), 2)
        clearance_items.append(
            {
                "sku_id": item["sku_id"],
                "product_name": item.get("product_name") or sku.get("product_name"),
                "brand": item.get("brand") or sku.get("brand") or "Unknown",
                "current_stock": _to_int(item.get("current_stock"), _to_int(sku.get("current_stock"), 0)),
                "age_days": _to_int(sku.get("days_since_launch"), 180),
                "suggested_price_usd": suggested_price,
                "recovered_cash_usd": recovered_cash,
                "urgency": PRIORITY_URGENCY.get(str(item.get("priority", "this_week")), "high"),
            }
        )

    hold_items = []
    for item in promotions_raw.get("hold_pricing", []):
        sku = inventory_sku_map.get(item["sku_id"], {})
        hold_items.append(
            {
                "sku_id": item["sku_id"],
                "product_name": item.get("product_name") or sku.get("product_name"),
                "brand": item.get("brand") or sku.get("brand") or "Unknown",
                "reason": item.get("reason", ""),
                "margin_pct": round(_to_float(item.get("current_margin_pct"), _to_float(sku.get("margin_pct"), 0.0)), 1),
                "velocity": round(_to_float(sku.get("velocity_units_per_day"), 0.0), 2),
            }
        )

    seasonal_actions = []
    for item in promotions_raw.get("seasonal_actions", []):
        signal = str(item.get("signal", "normal"))
        action, category = SEASONAL_ACTIONS.get(signal, ("HOLD", "Market"))
        seasonal_actions.append(
            {
                "month": item.get("month", ""),
                "action": action,
                "category": category,
                "detail": item.get("action", ""),
            }
        )

    directives = []
    for item in promotions_raw.get("directives", []):
        category = str(item.get("category", "planning"))
        detail = item.get("directive", "")
        first_sentence = detail.split(". ", 1)[0].strip().rstrip(".")
        directives.append(
            {
                "owner": SERVICE_OWNERS.get(category, "Operations"),
                "title": first_sentence[:72] if first_sentence else "Directive",
                "detail": detail,
                "priority": "high" if _to_int(item.get("priority"), 99) <= 2 else "medium" if _to_int(item.get("priority"), 99) <= 5 else "low",
            }
        )

    return {
        "inventory": {
            "metrics": {
                "total_skus": _to_int(inventory_metrics_raw.get("total_skus"), len(inventory_skus)),
                "total_units": _to_int(inventory_metrics_raw.get("total_units"), sum(item["current_stock"] for item in inventory_skus)),
                "inventory_value_at_cost_usd": round(_to_float(inventory_metrics_raw.get("inventory_at_cost_usd"), 0.0), 2),
                "inventory_value_at_retail_usd": round(_to_float(inventory_metrics_raw.get("inventory_at_retail_usd"), 0.0), 2),
                "blended_margin_pct": round(_to_float(inventory_metrics_raw.get("blended_margin_pct"), 0.0), 1),
                "median_days_of_supply": _median_days(inventory_skus),
                "critical_stockouts": _to_int(inventory_metrics_raw.get("critical_stockout_skus"), 0),
                "dead_stock_skus": sum(1 for item in inventory_skus if item["health"] == "dead"),
                "excess_stock_skus": sum(1 for item in inventory_skus if item["health"] == "excess"),
                "healthy_skus": sum(1 for item in inventory_skus if item["health"] == "healthy"),
            },
            "sku_analysis": inventory_skus,
            "category_summary": inventory_category_summary,
            "alerts": _inventory_alerts(raw_report.get("inventory", {}).get("alerts", []), inventory_sku_map),
        },
        "competitor": {
            "market_overview": {
                "skus_tracked": _to_int(competitor_market_overview_raw.get("products_analyzed"), len(competitor_positions)),
                "competitor_records": _to_int(raw_report.get("metadata", {}).get("competitor_records"), 0),
                "shops_covered": len(load_scrape_manifest().get("shops", {})),
                "avg_price_gap_pct": round(_to_float(competitor_market_overview_raw.get("avg_price_gap_pct"), 0.0), 1),
                "overpriced_skus": _to_int(competitor_market_overview_raw.get("products_overpriced"), 0),
                "underpriced_skus": _to_int(competitor_market_overview_raw.get("products_underpriced"), 0),
                "at_market_skus": _to_int(competitor_market_overview_raw.get("position_distribution", {}).get("at_market"), 0),
                "data_freshness_hours": competitor_freshness,
            },
            "sku_positioning": competitor_positions,
            "brand_summary": brand_summary,
            "category_summary": competitor_category_summary,
            "opportunities": opportunities,
        },
        "promotions": {
            "hold_pricing": hold_items,
            "promote": promote_items,
            "markdown": markdown_items,
            "clearance": clearance_items,
            "seasonal_actions": seasonal_actions,
            "directives": directives,
            "summary": {
                "hold_count": _to_int(promotions_raw.get("summary", {}).get("hold_count"), len(hold_items)),
                "promote_count": _to_int(promotions_raw.get("summary", {}).get("promote_count"), len(promote_items)),
                "markdown_count": _to_int(promotions_raw.get("summary", {}).get("markdown_count"), len(markdown_items)),
                "clearance_count": _to_int(promotions_raw.get("summary", {}).get("clearance_count"), len(clearance_items)),
            },
        },
        "metadata": {
            "generated_at": report_generated_at(),
            "engine_version": raw_report.get("metadata", {}).get("engine_version", "1.0.0"),
            "market": "Lebanon",
            "currency": "fresh USD",
            "data_window_days": DEFAULT_REPORT_WINDOW_DAYS,
            "source": "stylepulse-report",
        },
    }


def build_scrape_runs() -> list[dict[str, Any]]:
    database_rows = _read_intel_rows(
        """
        select id, shop_code, item_count, ingest_status, started_at, finished_at, created_at
        from intel.scrape_runs
        order by created_at desc
        limit 100
        """
    )
    if database_rows is not None:
        return [
            {
                "id": str(row["id"]),
                "shop": row["shop_code"],
                "started_at": _as_iso(row["started_at"] or row["created_at"]),
                "finished_at": _as_iso(row["finished_at"] or row["created_at"]),
                "status": "success" if row["ingest_status"] == "succeeded" else "failed",
                "items_scraped": _to_int(row["item_count"]),
                "valid_rows": _to_int(row["item_count"]) if row["ingest_status"] == "succeeded" else 0,
            }
            for row in database_rows
        ]

    manifest = load_scrape_manifest()
    runs: list[dict[str, Any]] = []
    for shop, meta in manifest.get("shops", {}).items():
        source_path = str(meta.get("source_json") or meta.get("source_csv") or "")
        started_at = _timestamp_from_token(source_path)
        stable_json = SCRAPING_OUTPUT_ROOT / shop / "records.json"
        if stable_json.exists():
            finished_at = datetime.fromtimestamp(stable_json.stat().st_mtime, tz=timezone.utc)
        else:
            finished_at = started_at or datetime.now(timezone.utc)
        valid_rows = _to_int(meta.get("valid_count"), 0)
        items_scraped = _to_int(meta.get("row_count"), 0)
        status = "success" if valid_rows == items_scraped else "partial" if valid_rows > 0 else "failed"
        runs.append(
            {
                "id": _stable_id("scrape", shop, source_path),
                "shop": shop,
                "started_at": (started_at or finished_at - timedelta(minutes=10)).isoformat(),
                "finished_at": finished_at.isoformat(),
                "status": status,
                "items_scraped": items_scraped,
                "valid_rows": valid_rows,
            }
        )
    runs.sort(key=lambda item: item["started_at"], reverse=True)
    return runs


def build_competitor_latest(limit: int = 50) -> list[dict[str, Any]]:
    database_rows = _read_intel_rows(
        """
        select shop_code, product_key, competitor_product_id, product_name, brand_name,
               competitor_price, competitor_sale_price, currency,
               is_on_sale, availability, source_url, last_seen_at
        from intel.competitor_products_latest
        order by last_seen_at desc
        limit %s
        """,
        (limit,),
    )
    if database_rows is not None:
        def _price_usd(row: dict[str, Any]) -> float:
            if "competitor_price" in row:
                return effective_competitor_price_usd(
                    row.get("competitor_price"),
                    row.get("competitor_sale_price"),
                    row.get("currency"),
                    row.get("is_on_sale"),
                ) or 0.0
            return _to_float(row.get("price_usd"), 0.0)

        return [
            {
                "shop": row["shop_code"],
                "external_id": row["competitor_product_id"] or row["product_key"],
                "product_name": row["product_name"],
                "brand": row["brand_name"] or "Unknown",
                "price_usd": _price_usd(row),
                "on_sale": bool(row["is_on_sale"]),
                "in_stock": str(row["availability"] or "").lower() == "in_stock",
                "url": row["source_url"] or "",
                "last_seen": _as_iso(row["last_seen_at"]),
            }
            for row in database_rows
        ]

    manifest = load_scrape_manifest()
    rows: list[dict[str, Any]] = []
    for shop in manifest.get("shops", {}):
        stable_json = SCRAPING_OUTPUT_ROOT / shop / "records.json"
        if not stable_json.exists():
            continue
        try:
            records = _read_json(stable_json)
        except json.JSONDecodeError:
            continue
        for record in records:
            price = effective_competitor_price_usd(
                record.get("competitor_price"),
                record.get("competitor_sale_price"),
                record.get("currency"),
                record.get("is_on_sale"),
            ) or 0.0
            rows.append(
                {
                    "shop": shop,
                    "external_id": record.get("competitor_product_id") or _stable_id("prod", shop, record.get("source_url")),
                    "product_name": record.get("product_name") or "Unknown Product",
                    "brand": record.get("brand_name") or "Unknown",
                    "price_usd": round(price, 2),
                    "on_sale": bool(record.get("is_on_sale")),
                    "in_stock": str(record.get("availability", "")).lower() == "in_stock",
                    "url": record.get("source_url", ""),
                    "last_seen": record.get("scraped_at") or _file_iso_timestamp(stable_json),
                }
            )
    rows.sort(key=lambda item: item["last_seen"], reverse=True)
    return rows[:limit]


def _merge_product_context(*sources: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in sources:
        for key, value in source.items():
            if value not in (None, ""):
                merged[key] = value
    return merged


def build_competitor_signals(sku_id: str, product_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    products = load_products_index()
    latest_states = load_latest_state_index()
    product = products.get(sku_id, {})
    state = latest_states.get(sku_id, {})
    processor_product = _merge_product_context(
        product,
        {
            "sku_id": sku_id,
            "retail_price_usd": state.get("retail_price_usd"),
            "category": state.get("category"),
        },
        product_payload or {},
    )
    processor_product["sku_id"] = sku_id
    return build_competitor_signals_for_product(processor_product)


def prepare_ie2_request(sku_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    products = load_products_index()
    inventory_rows = load_inventory_index()
    latest_states = load_latest_state_index()
    product = products.get(sku_id, {})
    inventory_row = inventory_rows.get(sku_id, {})
    state = latest_states.get(sku_id, {})

    normalized = dict(payload)
    normalized["sku_id"] = sku_id
    normalized.setdefault("product_name", product.get("product_name") or inventory_row.get("product_name"))
    normalized.setdefault("brand", product.get("brand") or inventory_row.get("brand"))
    normalized.setdefault("category", _friendly_category(state.get("category") or product.get("system_category")))
    normalized.setdefault("retail_price_usd", _to_float(inventory_row.get("retail_price_usd"), _to_float(product.get("retail_price_usd"), 0.0)))
    normalized.setdefault("cost_price_usd", _to_float(inventory_row.get("cost_price_usd"), _to_float(product.get("cost_price_usd"), 0.0)))
    normalized.setdefault("current_stock", _to_int(inventory_row.get("current_stock"), 0))
    normalized.setdefault("initial_stock", _to_int(state.get("inventory_initial_stock"), _to_int(product.get("initial_stock"), max(_to_int(inventory_row.get("current_stock"), 1), 1))))
    normalized.setdefault("days_since_launch", _to_int(state.get("days_since_launch"), 180))
    normalized.setdefault("days_since_last_discount", _to_int(state.get("days_since_last_discount"), 999))
    normalized.setdefault("days_at_current_price", _to_int(state.get("days_at_current_price"), 30))

    competitor_signals = dict(normalized.get("competitor_signals") or {})
    derived_signals = build_competitor_signals(sku_id, normalized)

    if not competitor_signals or _to_int(competitor_signals.get("num_competitors_tracked"), 0) <= 0:
        competitor_signals = derived_signals
    else:
        price_gap = _to_float(competitor_signals.get("price_gap_pct"), derived_signals["price_gap_pct"])
        competitor_signals["sku_id"] = sku_id
        competitor_signals["price_gap_pct"] = round(price_gap / 100, 4) if abs(price_gap) > 1 else round(price_gap, 4)
        competitor_signals["price_trend_direction"] = {
            "up": "RISING",
            "down": "FALLING",
            "flat": "STABLE",
            "rising": "RISING",
            "falling": "FALLING",
            "stable": "STABLE",
        }.get(str(competitor_signals.get("price_trend_direction", "STABLE")).strip().lower(), "STABLE")
        competitor_signals.setdefault("cheapest_competitor_name", derived_signals["cheapest_competitor_name"])
        competitor_signals.setdefault("data_freshness_hours", derived_signals["data_freshness_hours"])
        competitor_signals.setdefault("confidence_score", derived_signals["confidence_score"])
        competitor_signals.setdefault("fallback_used", derived_signals["fallback_used"])
        competitor_signals.setdefault("fallback_reason", derived_signals["fallback_reason"])
        competitor_signals.setdefault("match_type", "provided_signals")
        competitor_signals.setdefault("match_score", derived_signals.get("match_score", 0.0))
        competitor_signals.setdefault("timestamp", derived_signals["timestamp"])

    normalized["competitor_signals"] = competitor_signals
    return normalized


def serialize_frontend_recommendation(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        payload = result.model_dump(mode="json")
    elif isinstance(result, dict):
        payload = dict(result)
    else:
        raise TypeError("Unsupported recommendation payload")

    shap_items = []
    for item in payload.get("shap_top5", []):
        shap_items.append(
            {
                "feature": item.get("feature_name", item.get("feature", "feature")),
                "impact": round(_to_float(item.get("shap_value"), _to_float(item.get("impact"), 0.0)), 3),
                "direction": (
                    "positive"
                    if item.get("direction") in {"increases_probability", "positive"}
                    else "negative"
                ),
            }
        )

    rule_override = payload.get("rule_override")
    if isinstance(rule_override, dict):
        rule_override = rule_override.get("rule_id")

    return {
        "sku_id": payload.get("sku_id"),
        "product_name": payload.get("product_name"),
        "recommendation": payload.get("recommendation"),
        "confidence": round(_to_float(payload.get("confidence"), 0.0), 4),
        "explanation": payload.get("explanation", ""),
        "shap_top5": shap_items,
        "rule_override": rule_override,
        "fallback_used": bool(payload.get("fallback_used")),
        "suggested_discount_pct": payload.get("suggested_discount_pct"),
        "suggested_price_usd": payload.get("suggested_price_usd"),
        "margin_after_action_pct": payload.get("margin_after_action_pct"),
        "model_version": payload.get("model_version", "unknown"),
        "processing_time_ms": _to_int(payload.get("processing_time_ms"), 0),
        "requires_human_approval": bool(payload.get("requires_human_approval", True)),
    }

