"""
Build a larger RDS-backed candidate training dataset for IE2.

The script is intentionally candidate-only: it reads historical competitor
snapshots, reconstructs product-week inventory states where possible, adds
rolling generalization features, applies business-only weak labels, and can
create controlled augmentation rows without touching the production model.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from services.decision_intelligence.features.augment_training_dataset import build_augmented_training_dataset
from services.decision_intelligence.features.build_ai_labeled_dataset import _score_row
from services.decision_intelligence.features import clean_competitors as shared_matcher
from services.decision_intelligence.features.engineer import compute_state_features
from services.decision_intelligence.training.baseline import _assign_label


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATES_OUTPUT = ROOT / "data" / "features" / "rds_product_week_states.csv"
DEFAULT_TRAINING_OUTPUT = ROOT / "data" / "features" / "rds_training_dataset.csv"
DEFAULT_AI_OUTPUT = ROOT / "data" / "features" / "rds_ai_labeled_dataset.csv"
DEFAULT_AUGMENTED_TRAINING_OUTPUT = ROOT / "data" / "features" / "rds_training_dataset_augmented.csv"
DEFAULT_AUGMENTED_AI_OUTPUT = ROOT / "data" / "features" / "rds_ai_labeled_dataset_augmented.csv"
DEFAULT_SUMMARY_OUTPUT = ROOT / "data" / "reports" / "rds_expanded_training_dataset_summary.json"
DEFAULT_REVIEW_OUTPUT = ROOT / "data" / "reports" / "rds_label_review_candidates.csv"
DEFAULT_AUGMENTATION_SUMMARY_OUTPUT = ROOT / "data" / "reports" / "rds_training_dataset_augmentation_summary.json"

CURRENT_BASELINE_TRAINING_ROWS = 5968
LOW_CONFIDENCE_THRESHOLD = 0.68

LABEL_PROMPT_EXCLUDED_FIELDS = {
    "model_only_prediction",
    "model_only_confidence",
    "model_only_probabilities",
    "system_prediction",
    "system_confidence",
    "system_rule_id",
    "system_fallback_used",
    "expected_label",
    "ai_label",
    "ai_label_rationale",
    "ai_label_confidence",
    "audit_flags",
}

BUSINESS_LABEL_PAYLOAD_COLUMNS = [
    "sku_id",
    "product_name",
    "brand",
    "category",
    "retail_price_usd",
    "cost_price_usd",
    "current_stock",
    "initial_stock",
    "total_qty",
    "days_since_launch",
    "days_since_last_discount",
    "days_at_current_price",
    "days_of_supply",
    "current_margin_pct",
    "season_sell_through_pct",
    "price_gap_pct",
    "competitors_on_sale",
    "competitors_out_of_stock",
    "num_competitors",
    "market_position",
    "match_type",
    "match_score",
    "seasonality_score",
    "event_proximity_score",
]


def load_dotenv_if_present(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _db_url(explicit: str | None = None) -> str:
    value = explicit or os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_DSN") or os.environ.get("RDS_DATABASE_URL")
    if not value:
        raise RuntimeError("No RDS URL found. Set DATABASE_URL, POSTGRES_DSN, or RDS_DATABASE_URL in .env.")
    return value


def _connect(db_url: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise SystemExit("Missing dependency: psycopg. Run: pip install psycopg[binary]") from exc
    return psycopg.connect(db_url, row_factory=dict_row)


def _query_df(conn, sql: str) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql)
        return pd.DataFrame(cur.fetchall())


def audit_rds(conn) -> dict[str, Any]:
    snapshots = _query_df(
        conn,
        """
        select count(*)::bigint as snapshot_rows,
               count(distinct scrape_run_id)::bigint as scrape_runs,
               count(distinct shop_code)::bigint as shops,
               count(distinct nullif(style_code, ''))::bigint as snapshot_style_codes,
               min(snapshot_at) as first_snapshot_at,
               max(snapshot_at) as last_snapshot_at
        from intel.competitor_product_snapshots
        where data_valid = true
        """,
    ).iloc[0].to_dict()
    catalog = _query_df(
        conn,
        """
        select count(*)::bigint as sku_count,
               count(distinct nullif(style_code, ''))::bigint as catalog_style_codes
        from core.sku_variants
        where status = 'active'
        """,
    ).iloc[0].to_dict()
    exact = _query_df(
        conn,
        """
        select count(distinct s.style_code)::bigint as exact_style_codes
        from intel.competitor_product_snapshots s
        join core.sku_variants v
          on s.style_code = v.style_code
        where s.data_valid = true
          and nullif(s.style_code, '') is not null
          and nullif(v.style_code, '') is not null
          and v.status = 'active'
        """,
    ).iloc[0].to_dict()
    weeks = _query_df(
        conn,
        """
        select count(distinct date_trunc('week', snapshot_at)::date)::bigint as scrape_weeks
        from intel.competitor_product_snapshots
        where data_valid = true
        """,
    ).iloc[0].to_dict()

    sku_count = int(catalog.get("sku_count") or 0)
    scrape_weeks = int(weeks.get("scrape_weeks") or 0)
    exact_style_codes = int(exact.get("exact_style_codes") or 0)
    catalog_style_codes = max(int(catalog.get("catalog_style_codes") or 0), 1)
    snapshot_rows = int(snapshots.get("snapshot_rows") or 0)
    return {
        **_json_safe(snapshots),
        **_json_safe(catalog),
        **_json_safe(exact),
        **_json_safe(weeks),
        "estimated_product_week_capacity": sku_count * scrape_weeks,
        "exact_style_coverage_ratio": round(exact_style_codes / catalog_style_codes, 4),
        "data_sufficiency_hint": "ok" if snapshot_rows > 0 and scrape_weeks >= 3 else "insufficient_history",
    }


def load_rds_inputs(db_url: str, *, limit_snapshots: int | None = None) -> dict[str, Any]:
    limit_clause = f" limit {int(limit_snapshots)}" if limit_snapshots else ""
    with _connect(db_url) as conn:
        audit = audit_rds(conn)
        catalog = _query_df(
            conn,
            """
            select v.tenant_id::text as tenant_id,
                   v.id::text as variant_id,
                   v.sku_id,
                   v.style_code,
                   p.brand,
                   p.name as product_name,
                   p.category,
                   p.gender_target,
                   p.season,
                   p.created_at as product_created_at,
                   v.created_at as variant_created_at,
                   coalesce(v.cost_price_usd, 0) as cost_price_usd,
                   coalesce(price.amount, 0) as retail_price_usd,
                   coalesce(stock.current_stock, 0) as current_stock,
                   coalesce(init.initial_stock, stock.current_stock, 0) as initial_stock
            from core.sku_variants v
            join core.products p on p.id = v.product_id
            left join lateral (
                select amount from core.prices
                where variant_id = v.id and price_type = 'retail' and valid_to is null
                order by valid_from desc
                limit 1
            ) price on true
            left join lateral (
                select sum(quantity_on_hand)::int as current_stock
                from core.inventory_balances
                where variant_id = v.id
            ) stock on true
            left join lateral (
                select sum(greatest(quantity_delta, 0))::int as initial_stock
                from core.inventory_movements
                where variant_id = v.id
                  and movement_type in ('initial_stock', 'purchase_receipt')
            ) init on true
            where v.status = 'active'
              and p.status = 'active'
            """,
        )
        snapshots = _query_df(
            conn,
            f"""
            select s.id::text as snapshot_id,
                   s.shop_code,
                   s.scrape_run_id,
                   s.snapshot_at,
                   s.product_key,
                   s.competitor_product_id,
                   s.style_code,
                   s.sku_id as competitor_sku_id,
                   s.brand_name,
                   s.product_name,
                   s.category,
                   s.gender_target,
                   s.competitor_price,
                   s.competitor_sale_price,
                   s.discount_pct,
                   s.is_on_sale,
                   s.availability,
                   s.currency,
                   s.source_url
            from intel.competitor_product_snapshots s
            where s.data_valid = true
              and (
                s.competitor_price is not null
                or s.competitor_sale_price is not null
                or lower(coalesce(s.availability, '')) in ('out_of_stock', 'sold_out', 'unavailable')
              )
            {limit_clause}
            """,
        )
        movements = _query_df(
            conn,
            """
            select v.sku_id,
                   m.variant_id::text as variant_id,
                   m.movement_type,
                   m.quantity_delta,
                   m.created_at
            from core.inventory_movements m
            join core.sku_variants v on v.id = m.variant_id
            """,
        )
        sales = _query_df(
            conn,
            """
            select v.sku_id,
                   t.sold_at,
                   l.quantity,
                   l.unit_price_usd,
                   l.discount_pct
            from core.sales_transaction_lines l
            join core.sales_transactions t on t.id = l.sales_transaction_id
            join core.sku_variants v on v.id = l.variant_id
            """,
        )
    return {"catalog": catalog, "snapshots": snapshots, "movements": movements, "sales": sales, "audit": audit}


def _normalize_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower().strip() if ch.isalnum())


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("-", " ").replace("_", " ").split())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None) or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in ("", None) or pd.isna(value):
            return default
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _effective_price(row: pd.Series) -> float | None:
    currency = str(row.get("currency") or "USD").strip().upper()
    sale = _safe_float(row.get("competitor_sale_price"), 0.0)
    price = _safe_float(row.get("competitor_price"), 0.0)
    if currency == "LBP":
        sale *= shared_matcher.LBP_TO_USD
        price *= shared_matcher.LBP_TO_USD
    if sale > 0:
        return sale
    if price > 0:
        return price
    return None


def _availability_bucket(value: Any) -> str:
    normalized = _normalize_text(value).replace(" ", "_")
    if normalized in {"out_of_stock", "sold_out", "unavailable", "no_stock"}:
        return "OUT_OF_STOCK"
    if normalized in {"low_stock", "few_left"}:
        return "LOW_STOCK"
    if normalized:
        return "IN_STOCK"
    return "UNKNOWN"


def _prepare_catalog(catalog: pd.DataFrame) -> pd.DataFrame:
    df = catalog.copy()
    if df.empty:
        raise ValueError("Catalog query returned no active SKUs.")
    df["sku_id"] = df["sku_id"].astype(str)
    df["style_key"] = df["style_code"].map(_normalize_key)
    df["sku_key"] = df["sku_id"].map(_normalize_key)
    df["brand_key"] = df["brand"].map(_normalize_text)
    df["name_key"] = df["product_name"].map(_normalize_text)
    df["brand_normalized"] = df["brand"].map(shared_matcher.normalize_brand)
    df["style_code_normalized"] = df["style_code"].map(shared_matcher.normalize_style_code)
    df["category_normalized"] = df.apply(
        lambda row: shared_matcher.normalize_category(row.get("category"), row.get("product_name")),
        axis=1,
    )
    df["gender_normalized"] = df.apply(
        lambda row: shared_matcher.normalize_gender(row.get("gender_target"), row.get("product_name")),
        axis=1,
    )
    df["catalog_product_name"] = df["product_name"]
    df["category"] = df["category"].fillna("other").astype(str).str.lower().str.replace(" ", "_", regex=False)
    for column in ["retail_price_usd", "cost_price_usd", "current_stock", "initial_stock"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    df["current_stock"] = df["current_stock"].clip(lower=0).astype(int)
    df["initial_stock"] = df[["initial_stock", "current_stock"]].max(axis=1).clip(lower=1).astype(int)
    df = df[(df["sku_id"] != "") & (df["retail_price_usd"] > 0)].copy()
    if df.empty:
        raise ValueError("No catalog rows have a valid SKU and retail price.")
    return df


def _prepare_snapshots(snapshots: pd.DataFrame) -> pd.DataFrame:
    df = snapshots.copy()
    if df.empty:
        raise ValueError("RDS competitor snapshots returned no usable rows.")
    df["snapshot_at"] = pd.to_datetime(df["snapshot_at"], utc=True, errors="coerce")
    df = df.dropna(subset=["snapshot_at"]).copy()
    df["week_of"] = df["snapshot_at"].dt.tz_convert(None).dt.to_period("W-MON").dt.start_time.dt.date.astype(str)
    df["style_key"] = df["style_code"].map(_normalize_key)
    df["competitor_sku_key"] = df["competitor_sku_id"].map(_normalize_key)
    df["brand_key"] = df["brand_name"].map(_normalize_text)
    df["name_key"] = df["product_name"].map(_normalize_text)
    df["brand_name"] = df["brand_name"].map(shared_matcher.normalize_brand)
    df["style_code_normalized"] = df["style_code"].map(shared_matcher.normalize_style_code)
    df["category_normalized"] = df.apply(
        lambda row: shared_matcher.normalize_category(row.get("category"), row.get("product_name")),
        axis=1,
    )
    df["gender_normalized"] = df.apply(
        lambda row: shared_matcher.normalize_gender(row.get("gender_target"), row.get("product_name")),
        axis=1,
    )
    df["effective_competitor_price_usd"] = df.apply(_effective_price, axis=1)
    df["availability_bucket"] = df["availability"].map(_availability_bucket)
    df["is_on_sale"] = df["is_on_sale"].fillna(False).astype(bool)
    return df


def match_snapshots_to_catalog(snapshots: pd.DataFrame, catalog: pd.DataFrame) -> pd.DataFrame:
    exact = snapshots[snapshots["style_key"].ne("")].merge(
        catalog[catalog["style_key"].ne("")],
        on="style_key",
        how="inner",
        suffixes=("_competitor", "_catalog"),
    )
    exact["match_type"] = "exact_style"
    exact["match_score"] = 1.0
    exact["match_reason"] = "competitor style_code matched catalog style_code"

    matched_ids = set(exact["snapshot_id"].astype(str).tolist()) if not exact.empty else set()
    unmatched = snapshots[~snapshots["snapshot_id"].astype(str).isin(matched_ids)].copy()
    sku = unmatched[unmatched["competitor_sku_key"].ne("")].merge(
        catalog[catalog["sku_key"].ne("")],
        left_on="competitor_sku_key",
        right_on="sku_key",
        how="inner",
        suffixes=("_competitor", "_catalog"),
    )
    sku["match_type"] = "exact_sku"
    sku["match_score"] = 0.98
    sku["match_reason"] = "competitor sku_id matched catalog sku_id"

    matched_ids.update(set(sku["snapshot_id"].astype(str).tolist()) if not sku.empty else set())
    fallback = _fallback_text_matches(snapshots[~snapshots["snapshot_id"].astype(str).isin(matched_ids)], catalog)
    matched = pd.concat([exact, sku, fallback], ignore_index=True, sort=False)
    if matched.empty:
        return pd.DataFrame()
    matched = matched.sort_values(["snapshot_id", "match_score"], ascending=[True, False])
    return matched.drop_duplicates(subset=["snapshot_id", "sku_id"], keep="first")


def _fallback_text_matches(snapshots: pd.DataFrame, catalog: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if snapshots.empty or catalog.empty:
        return pd.DataFrame()

    key_columns = [
        "shop_code",
        "brand_name",
        "product_name",
        "category_normalized",
        "gender_normalized",
        "effective_competitor_price_usd",
    ]
    work = snapshots.copy()
    work["_fallback_cache_key"] = work[key_columns].apply(
        lambda row: tuple("" if pd.isna(value) else str(value) for value in row),
        axis=1,
    )
    unique_snapshots = work.drop_duplicates(subset=["_fallback_cache_key"]).copy()

    by_family = {
        family: group.copy()
        for family, group in catalog.groupby(["brand_normalized", "category_normalized", "gender_normalized"], dropna=False)
        if family[0]
    }
    match_cache: dict[tuple[str, ...], tuple[float, str, str, dict[str, Any]]] = {}
    for _, snap in unique_snapshots.iterrows():
        family = (snap.get("brand_name"), snap.get("category_normalized"), snap.get("gender_normalized"))
        candidates = by_family.get(family)
        if candidates is None or candidates.empty:
            continue
        best: tuple[float, str, str, pd.Series] | None = None
        for _, candidate in candidates.iterrows():
            match_type, match_score, match_reason = shared_matcher.score_fallback_match(candidate, snap)
            if match_type is None or match_score <= shared_matcher.MATCH_SCORE_THRESHOLD:
                continue
            if best is None or match_score > best[0]:
                best = (match_score, match_type, match_reason, candidate)
        if best is None:
            continue
        score, match_type, match_reason, candidate = best
        match_cache[snap["_fallback_cache_key"]] = (score, match_type, match_reason, candidate.to_dict())

    for _, snap in work.iterrows():
        cached = match_cache.get(snap["_fallback_cache_key"])
        if cached is None:
            continue
        score, match_type, match_reason, candidate = cached
        payload = {**snap.to_dict(), **candidate}
        payload.pop("_fallback_cache_key", None)
        payload["match_type"] = match_type
        payload["match_score"] = round(float(score), 4)
        payload["match_reason"] = match_reason
        rows.append(payload)
    return pd.DataFrame(rows)


def aggregate_competitors_by_week(matches: pd.DataFrame) -> pd.DataFrame:
    if matches.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for (sku_id, week_of), group in matches.groupby(["sku_id", "week_of"], dropna=False):
        price_rows = group.dropna(subset=["effective_competitor_price_usd"])
        shops = group["shop_code"].astype(str)
        best_match = group.sort_values("match_score", ascending=False).iloc[0]
        rows.append(
            {
                "sku_id": sku_id,
                "week_of": week_of,
                "competitor_min_price_usd": price_rows["effective_competitor_price_usd"].min() if not price_rows.empty else None,
                "competitor_avg_price_usd": price_rows["effective_competitor_price_usd"].mean() if not price_rows.empty else None,
                "competitor_max_price_usd": price_rows["effective_competitor_price_usd"].max() if not price_rows.empty else None,
                "num_competitors": int(shops.nunique()),
                "competitors_on_sale_count": int(group.loc[group["is_on_sale"], "shop_code"].astype(str).nunique()),
                "competitors_out_of_stock_count": int(group.loc[group["availability_bucket"].eq("OUT_OF_STOCK"), "shop_code"].astype(str).nunique()),
                "match_type": str(best_match.get("match_type") or "similar_product"),
                "match_score": round(float(group["match_score"].mean()), 4),
                "matched_products_count": int(len(group)),
                "has_competitor_data": 1,
            }
        )
    return pd.DataFrame(rows)


def build_product_week_states(inputs: dict[str, Any]) -> pd.DataFrame:
    catalog = _prepare_catalog(inputs["catalog"])
    snapshots = _prepare_snapshots(inputs["snapshots"])
    competitor_week = aggregate_competitors_by_week(match_snapshots_to_catalog(snapshots, catalog))
    weeks = sorted(snapshots["week_of"].dropna().unique().tolist())
    if not weeks:
        raise ValueError("No valid scrape weeks found.")
    base = catalog.assign(_join_key=1).merge(pd.DataFrame({"week_of": weeks, "_join_key": 1}), on="_join_key").drop(columns="_join_key")
    states = base.merge(competitor_week, on=["sku_id", "week_of"], how="left")
    states["has_competitor_data"] = states["has_competitor_data"].fillna(0).astype(int)
    states["match_type"] = states["match_type"].fillna("no_match")
    states["match_score"] = pd.to_numeric(states["match_score"], errors="coerce").fillna(0.0)
    for column in ["num_competitors", "competitors_on_sale_count", "competitors_out_of_stock_count"]:
        states[column] = pd.to_numeric(states[column], errors="coerce").fillna(0).astype(int)
    states = _attach_inventory_history(states, inputs["movements"], inputs["sales"])
    states.loc[states["has_competitor_data"].eq(0), ["competitor_min_price_usd", "competitor_avg_price_usd", "competitor_max_price_usd"]] = 0.0
    states = states.drop_duplicates(subset=["sku_id", "week_of"], keep="first")
    states["state_id"] = states["sku_id"].astype(str) + "|" + states["week_of"].astype(str)
    return states


def _attach_inventory_history(states: pd.DataFrame, movements: pd.DataFrame, sales: pd.DataFrame) -> pd.DataFrame:
    df = states.copy()
    df["week_end"] = pd.to_datetime(df["week_of"], utc=True, errors="coerce") + pd.Timedelta(days=6, hours=23)
    movement_history_available = not movements.empty and {"sku_id", "quantity_delta", "created_at"}.issubset(movements.columns)
    sales_history_available = not sales.empty and {"sku_id", "quantity", "sold_at"}.issubset(sales.columns)
    df["inventory_history_quality"] = "current_stock_backfill"
    if movement_history_available:
        mv = movements.copy()
        mv["created_at"] = pd.to_datetime(mv["created_at"], utc=True, errors="coerce")
        mv = mv.dropna(subset=["created_at"])
        stocks: list[int] = []
        peaks: list[int] = []
        for _, row in df.iterrows():
            sku_movements = mv[mv["sku_id"].astype(str).eq(str(row["sku_id"]))]
            after_week = sku_movements[sku_movements["created_at"] > row["week_end"]]
            stock = _safe_int(row.get("current_stock")) - int(after_week["quantity_delta"].sum()) if not after_week.empty else _safe_int(row.get("current_stock"))
            before_week = sku_movements[sku_movements["created_at"] <= row["week_end"]]
            receipts = before_week[before_week["quantity_delta"] > 0]["quantity_delta"].sum()
            stocks.append(max(0, stock))
            peaks.append(max(stock, int(receipts), _safe_int(row.get("initial_stock")), 1))
        df["total_qty"] = stocks
        df["simulated_peak_stock"] = peaks
        df["inventory_history_quality"] = "movement_reconstructed"
    else:
        df["total_qty"] = df["current_stock"]
        df["simulated_peak_stock"] = df[["initial_stock", "current_stock"]].max(axis=1).clip(lower=1)
    if sales_history_available:
        sl = sales.copy()
        sl["sold_at"] = pd.to_datetime(sl["sold_at"], utc=True, errors="coerce")
        sl = sl.dropna(subset=["sold_at"])
        rolling_sales: list[float] = []
        for _, row in df.iterrows():
            start = row["week_end"] - pd.Timedelta(days=28)
            sku_sales = sl[sl["sku_id"].astype(str).eq(str(row["sku_id"])) & (sl["sold_at"] > start) & (sl["sold_at"] <= row["week_end"])]
            rolling_sales.append(float(sku_sales["quantity"].sum()) if not sku_sales.empty else 0.0)
        df["sales_units_last_28d"] = rolling_sales
        df["avg_daily_sales_28d"] = (df["sales_units_last_28d"] / 28.0).round(4)
    else:
        df["sales_units_last_28d"] = 0.0
        df["avg_daily_sales_28d"] = 0.0
    df["sell_through_proxy"] = (1.0 - (df["total_qty"] / df["simulated_peak_stock"].replace(0, 1))).clip(0.0, 1.0)
    created = pd.to_datetime(df["variant_created_at"].fillna(df.get("product_created_at")), utc=True, errors="coerce")
    week_dt = pd.to_datetime(df["week_of"], utc=True, errors="coerce")
    df["days_since_launch"] = ((week_dt - created).dt.days).fillna(180).clip(lower=0).astype(int)
    df["days_since_last_discount"] = 999
    df["days_at_current_price"] = 30
    return df.drop(columns=["week_end"], errors="ignore")


def engineer_rds_features(states: pd.DataFrame) -> pd.DataFrame:
    financial_profile = {
        "cashflow_summary": {"cash_runway_months": 3.0},
        "inventory_summary": {"total_cost_usd": 176000},
        "balance_sheet_summary": {"total_assets_usd": 214000},
    }
    features = pd.DataFrame([compute_state_features(row.to_dict(), financial_profile) for _, row in states.iterrows()])
    passthrough = [
        "state_id",
        "match_type",
        "match_score",
        "inventory_history_quality",
        "has_competitor_data",
        "competitor_min_price_usd",
        "competitor_avg_price_usd",
        "competitor_max_price_usd",
        "sales_units_last_28d",
        "avg_daily_sales_28d",
    ]
    features = features.merge(states[[col for col in passthrough if col in states.columns]], on="state_id", how="left")
    sales_velocity = pd.to_numeric(features.get("avg_daily_sales_28d"), errors="coerce").fillna(0.0)
    stock = pd.to_numeric(features["total_qty"], errors="coerce").fillna(0.0)
    mask = sales_velocity > 0
    features.loc[mask, "days_of_supply"] = (stock[mask] / sales_velocity[mask]).clip(lower=0, upper=9999).round(1)
    features["stock_coverage_ratio"] = (features["days_of_supply"] / 30.0).round(2)
    features["stockout_risk"] = (features["days_of_supply"] < 14).astype(int)
    features = _add_rolling_features(features)
    features["rules_label"] = features.apply(_assign_label, axis=1)
    features["row_source"] = "rds_snapshot_history"
    features["is_augmented"] = 0
    features["augmentation_family"] = ""
    features["anchor_state_id"] = ""
    features["sample_weight_hint"] = 1.0
    return features


def _add_rolling_features(features: pd.DataFrame) -> pd.DataFrame:
    df = features.copy()
    df["_week_dt"] = pd.to_datetime(df["week_of"], errors="coerce")
    df = df.sort_values(["sku_id", "_week_dt"])
    min_price = pd.to_numeric(df["competitor_min_price_usd"], errors="coerce").replace(0, pd.NA)
    price_gap = pd.to_numeric(df["price_gap_pct"], errors="coerce").fillna(0.0)
    on_sale = pd.to_numeric(df["competitors_on_sale"], errors="coerce").fillna(0.0)
    out_stock = pd.to_numeric(df["competitors_out_of_stock"], errors="coerce").fillna(0.0)
    num_comp = pd.to_numeric(df["num_competitors"], errors="coerce").replace(0, pd.NA)
    total_qty = pd.to_numeric(df["total_qty"], errors="coerce").fillna(0.0)
    sell_through = pd.to_numeric(df["season_sell_through_pct"], errors="coerce").fillna(0.0)
    grouped = df.groupby("sku_id", group_keys=False)
    df["competitor_price_trend_4w"] = _group_apply(grouped, lambda g: min_price.loc[g.index].pct_change(periods=4).fillna(0)).reset_index(level=0, drop=True).round(4)
    df["competitor_sale_frequency_4w"] = _group_apply(grouped, lambda g: (on_sale.loc[g.index] / num_comp.loc[g.index]).fillna(0).rolling(4, min_periods=1).mean()).reset_index(level=0, drop=True).round(4)
    df["competitor_oos_frequency_4w"] = _group_apply(grouped, lambda g: (out_stock.loc[g.index] / num_comp.loc[g.index]).fillna(0).rolling(4, min_periods=1).mean()).reset_index(level=0, drop=True).round(4)
    df["price_gap_volatility_4w"] = _group_apply(grouped, lambda g: price_gap.loc[g.index].rolling(4, min_periods=2).std().fillna(0)).reset_index(level=0, drop=True).round(4)
    df["stock_velocity_4w"] = _group_apply(grouped, lambda g: (-total_qty.loc[g.index].diff()).rolling(4, min_periods=1).mean().fillna(0)).reset_index(level=0, drop=True).round(4)
    df["sell_through_velocity_4w"] = _group_apply(grouped, lambda g: sell_through.loc[g.index].diff().rolling(4, min_periods=1).mean().fillna(0)).reset_index(level=0, drop=True).round(4)
    df["days_since_competitor_change"] = _group_apply(grouped, _days_since_comp_change).reset_index(level=0, drop=True)
    return df.drop(columns=["_week_dt"], errors="ignore")


def _group_apply(grouped, func):
    try:
        return grouped.apply(func, include_groups=False)
    except TypeError:
        return grouped.apply(func)


def _days_since_comp_change(group: pd.DataFrame) -> pd.Series:
    values: list[int] = []
    last_change: pd.Timestamp | None = None
    previous_gap: float | None = None
    for _, row in group.iterrows():
        week = pd.to_datetime(row.get("_week_dt"), errors="coerce")
        gap = _safe_float(row.get("price_gap_pct"))
        if previous_gap is None or abs(gap - previous_gap) >= 0.02 or last_change is None:
            last_change = week
            values.append(0)
        else:
            values.append(int((week - last_change).days) if pd.notna(week) and last_change is not None else 0)
        previous_gap = gap
    return pd.Series(values, index=group.index)


def apply_business_only_labels(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    labeled = features.copy()
    labels: list[str] = []
    confidences: list[float] = []
    rationales: list[str] = []
    audit_flags: list[str] = []
    for _, row in labeled.iterrows():
        _validate_business_label_payload(row.to_dict())
        ai_label, confidence, _scores, rationale = _score_row(row)
        labels.append(ai_label)
        confidences.append(confidence)
        rationales.append(rationale)
        audit_flags.append("|".join(_audit_flags(row, ai_label, confidence)))
    labeled["ai_label"] = labels
    labeled["expected_label"] = labels
    labeled["ai_label_confidence"] = confidences
    labeled["label_confidence"] = confidences
    labeled["ai_label_rationale"] = rationales
    labeled["audit_flags"] = audit_flags
    labeled["label_prompt_version"] = "business_only_retail_pricing_v1"
    labeled["labeler_model"] = "deterministic_business_heuristic"
    labeled["labeled_at"] = datetime.now(timezone.utc).isoformat()
    labeled["ai_label_disagrees_with_rules"] = (labeled["ai_label"].astype(str) != labeled["rules_label"].astype(str)).astype(int)

    review_mask = (
        (labeled["ai_label_confidence"] < LOW_CONFIDENCE_THRESHOLD)
        | labeled["ai_label"].eq("CLEAR")
        | labeled["match_type"].isin(["similar_product", "no_match"])
        | labeled["audit_flags"].str.contains("manual_review", na=False)
    )
    review = labeled.loc[review_mask].copy()
    random_review = _group_apply(
        labeled.groupby("ai_label", group_keys=False),
        lambda g: g.sample(min(20, len(g)), random_state=42),
    ).copy()
    review = pd.concat([review, random_review], ignore_index=True).drop_duplicates(subset=["state_id"])
    return labeled, review


def _validate_business_label_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = {column: row.get(column) for column in BUSINESS_LABEL_PAYLOAD_COLUMNS if column in row}
    leaked = set(payload).intersection(LABEL_PROMPT_EXCLUDED_FIELDS)
    if leaked:
        raise ValueError(f"Business-only label payload leaked evaluation fields: {sorted(leaked)}")
    return payload


def _audit_flags(row: pd.Series, label: str, confidence: float) -> list[str]:
    flags: list[str] = []
    qty = _safe_float(row.get("total_qty"))
    margin = _safe_float(row.get("current_margin_pct"))
    gap = _safe_float(row.get("price_gap_pct"))
    dos = _safe_float(row.get("days_of_supply"))
    sell = _safe_float(row.get("season_sell_through_pct"))
    match_type = str(row.get("match_type") or "no_match")
    if qty < 15:
        flags.append("low_stock")
    if margin < 32:
        flags.append("thin_margin")
    if gap >= 0.12:
        flags.append("overpriced")
    if gap <= -0.05 and qty >= 20:
        flags.append("demand_capture")
    if match_type in {"similar_product", "no_match"}:
        flags.append("weak_competitor_match")
    if dos >= 120 and sell <= 0.25:
        flags.append("stale_inventory")
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        flags.append("low_label_confidence")
    if label in {"CLEAR", "MARKDOWN"} and match_type == "no_match":
        flags.append("manual_review_no_match_action")
    return flags


def postprocess_augmented_dataset(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    synthetic = pd.to_numeric(df.get("synthetic_is_augmented", 0), errors="coerce").fillna(0).astype(int)
    df["is_augmented"] = synthetic
    df["row_source"] = synthetic.map({0: "rds_snapshot_history", 1: "controlled_augmentation"})
    df["augmentation_family"] = _column_or_default(df, "synthetic_mutation_profile", "").fillna("")
    df["anchor_state_id"] = _column_or_default(df, "synthetic_anchor_state_id", "").fillna("")
    df["sample_weight_hint"] = synthetic.map({0: 1.0, 1: 0.45})
    df["label_confidence"] = pd.to_numeric(df.get("ai_label_confidence"), errors="coerce").fillna(0.0)
    df["expected_label"] = df.get("ai_label", "")
    df["audit_flags"] = [
        "|".join(_audit_flags(row, str(row.get("ai_label") or ""), _safe_float(row.get("ai_label_confidence"))))
        for _, row in df.iterrows()
    ]
    df["label_prompt_version"] = "business_only_retail_pricing_v1"
    df["labeler_model"] = "deterministic_business_heuristic"
    df["labeled_at"] = datetime.now(timezone.utc).isoformat()
    df.to_csv(path, index=False)
    return df


def _column_or_default(df: pd.DataFrame, column: str, default: Any) -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series([default] * len(df), index=df.index)


def build_dataset(
    *,
    db_url: str | None = None,
    states_output: Path = DEFAULT_STATES_OUTPUT,
    training_output: Path = DEFAULT_TRAINING_OUTPUT,
    ai_output: Path = DEFAULT_AI_OUTPUT,
    augmented_training_output: Path = DEFAULT_AUGMENTED_TRAINING_OUTPUT,
    augmented_ai_output: Path = DEFAULT_AUGMENTED_AI_OUTPUT,
    summary_output: Path = DEFAULT_SUMMARY_OUTPUT,
    review_output: Path = DEFAULT_REVIEW_OUTPUT,
    augmentation_summary_output: Path = DEFAULT_AUGMENTATION_SUMMARY_OUTPUT,
    audit_only: bool = False,
    skip_augmentation: bool = False,
    limit_snapshots: int | None = None,
    clear_count: int = 420,
    hold_count: int = 180,
    promote_count: int = 220,
    markdown_count: int = 240,
    max_copies_per_anchor: int = 3,
    seed: int = 42,
) -> dict[str, Any]:
    load_dotenv_if_present()
    resolved_db_url = _db_url(db_url)
    if audit_only:
        with _connect(resolved_db_url) as conn:
            audit = audit_rds(conn)
        summary = {"audit": audit, "credential_note": "Rotate exposed RDS password before production use."}
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(json.dumps(_json_safe(summary), indent=2) + "\n", encoding="utf-8")
        return summary

    inputs = load_rds_inputs(resolved_db_url, limit_snapshots=limit_snapshots)

    states = build_product_week_states(inputs)
    features = engineer_rds_features(states)
    labeled, review = apply_business_only_labels(features)

    states_output.parent.mkdir(parents=True, exist_ok=True)
    training_output.parent.mkdir(parents=True, exist_ok=True)
    ai_output.parent.mkdir(parents=True, exist_ok=True)
    review_output.parent.mkdir(parents=True, exist_ok=True)
    states.to_csv(states_output, index=False)
    features.to_csv(training_output, index=False)
    labeled.to_csv(ai_output, index=False)
    review.to_csv(review_output, index=False)

    augmented_report: dict[str, Any] | None = None
    final_df = labeled
    if not skip_augmentation:
        augmentation_anchor_ai_output = ai_output.with_name(f"{ai_output.stem}_augmentation_anchor.csv")
        augmented_report = build_augmented_training_dataset(
            training_dataset_path=training_output,
            ai_labels_path=augmentation_anchor_ai_output,
            augmented_training_output=augmented_training_output,
            augmented_ai_output=augmented_ai_output,
            summary_report_output=augmentation_summary_output,
            target_counts={"CLEAR": clear_count, "HOLD": hold_count, "PROMOTE": promote_count, "MARKDOWN": markdown_count},
            seed=seed,
            max_copies_per_anchor=max_copies_per_anchor,
            refresh_ai_labels=True,
        )
        final_df = postprocess_augmented_dataset(augmented_ai_output)

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "aws_rds_historical_competitor_snapshots",
        "audit": inputs["audit"],
        "outputs": {
            "states": str(states_output),
            "training_dataset": str(training_output),
            "ai_labeled_dataset": str(ai_output),
            "review_candidates": str(review_output),
            "augmented_training_dataset": str(augmented_training_output) if augmented_report else None,
            "augmented_ai_labeled_dataset": str(augmented_ai_output) if augmented_report else None,
        },
        "row_counts": {
            "states": int(len(states)),
            "training_rows": int(len(features)),
            "ai_labeled_rows": int(len(labeled)),
            "review_candidate_rows": int(len(review)),
            "final_candidate_rows": int(len(final_df)),
        },
        "label_distribution": final_df["ai_label"].value_counts().to_dict() if "ai_label" in final_df else {},
        "rules_distribution": final_df["rules_label"].value_counts().to_dict() if "rules_label" in final_df else {},
        "match_type_distribution": features["match_type"].value_counts().to_dict() if "match_type" in features else {},
        "inventory_history_quality_distribution": features["inventory_history_quality"].value_counts().to_dict()
        if "inventory_history_quality" in features
        else {},
        "augmentation": augmented_report,
        "current_baseline_training_rows": CURRENT_BASELINE_TRAINING_ROWS,
        "larger_than_current_baseline": int(len(final_df)) > CURRENT_BASELINE_TRAINING_ROWS,
        "credential_note": "Rotate the exposed RDS password before running against production data.",
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(_json_safe(summary), indent=2) + "\n", encoding="utf-8")
    return summary


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build RDS-backed expanded candidate training data.")
    parser.add_argument("--db-url", default=None, help="Optional DB URL override. Prefer .env DATABASE_URL.")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--skip-augmentation", action="store_true")
    parser.add_argument("--limit-snapshots", type=int, default=None)
    parser.add_argument("--states-output", type=Path, default=DEFAULT_STATES_OUTPUT)
    parser.add_argument("--training-output", type=Path, default=DEFAULT_TRAINING_OUTPUT)
    parser.add_argument("--ai-output", type=Path, default=DEFAULT_AI_OUTPUT)
    parser.add_argument("--augmented-training-output", type=Path, default=DEFAULT_AUGMENTED_TRAINING_OUTPUT)
    parser.add_argument("--augmented-ai-output", type=Path, default=DEFAULT_AUGMENTED_AI_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--review-output", type=Path, default=DEFAULT_REVIEW_OUTPUT)
    parser.add_argument("--augmentation-summary-output", type=Path, default=DEFAULT_AUGMENTATION_SUMMARY_OUTPUT)
    parser.add_argument("--clear-count", type=int, default=420)
    parser.add_argument("--hold-count", type=int, default=180)
    parser.add_argument("--promote-count", type=int, default=220)
    parser.add_argument("--markdown-count", type=int, default=240)
    parser.add_argument("--max-copies-per-anchor", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = build_dataset(
        db_url=args.db_url,
        states_output=args.states_output,
        training_output=args.training_output,
        ai_output=args.ai_output,
        augmented_training_output=args.augmented_training_output,
        augmented_ai_output=args.augmented_ai_output,
        summary_output=args.summary_output,
        review_output=args.review_output,
        augmentation_summary_output=args.augmentation_summary_output,
        audit_only=args.audit_only,
        skip_augmentation=args.skip_augmentation,
        limit_snapshots=args.limit_snapshots,
        clear_count=args.clear_count,
        hold_count=args.hold_count,
        promote_count=args.promote_count,
        markdown_count=args.markdown_count,
        max_copies_per_anchor=args.max_copies_per_anchor,
        seed=args.seed,
    )
    print(json.dumps(_json_safe(summary), indent=2))


if __name__ == "__main__":
    main()
