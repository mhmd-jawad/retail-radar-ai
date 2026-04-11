"""Create a stable one-version-per-shop output tree from timestamped scrape runs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUTS_DIR = ROOT / "data" / "outputs"
STABLE_OUTPUT_DIR = ROOT / "data" / "output"

SHOPS = [
    "adidas_lb",
    "mikesport",
    "tchooz",
    "shoesworld",
    "citysport",
    "kix",
    "marka_store",
]

COMBINED_PATTERNS = {
    "all_shops_full_records": "*_all_shops_full_records",
    "remaining_shops_full_records": "*_remaining_shops_full_records",
}


def main() -> int:
    STABLE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "shops": {},
        "combined": {},
    }

    for shop in SHOPS:
        shop_dir = OUTPUTS_DIR / shop
        latest_prefix = _latest_prefix(shop_dir, suffix="_records")
        if latest_prefix is None:
            continue

        source_csv = shop_dir / f"{latest_prefix}_{shop}_records.csv"
        source_json = shop_dir / f"{latest_prefix}_{shop}_records.json"
        target_dir = STABLE_OUTPUT_DIR / shop
        target_dir.mkdir(parents=True, exist_ok=True)

        target_csv = target_dir / "records.csv"
        target_json = target_dir / "records.json"
        shutil.copy2(source_csv, target_csv)
        shutil.copy2(source_json, target_json)

        stats = _csv_stats(target_csv)
        metadata = {
            "shop": shop,
            "source_csv": str(source_csv.relative_to(ROOT)),
            "source_json": str(source_json.relative_to(ROOT)),
            "stable_csv": str(target_csv.relative_to(ROOT)),
            "stable_json": str(target_json.relative_to(ROOT)),
            **stats,
        }
        _write_json(target_dir / "metadata.json", metadata)
        manifest["shops"][shop] = metadata

    combined_dir = STABLE_OUTPUT_DIR / "combined"
    combined_dir.mkdir(parents=True, exist_ok=True)
    for name, glob_pattern in COMBINED_PATTERNS.items():
        latest_prefix = _latest_top_level_prefix(glob_pattern)
        if latest_prefix is None:
            continue

        source_csv = OUTPUTS_DIR / f"{latest_prefix}_{name}.csv"
        source_json = OUTPUTS_DIR / f"{latest_prefix}_{name}.json"
        target_csv = combined_dir / f"{name}.csv"
        target_json = combined_dir / f"{name}.json"
        shutil.copy2(source_csv, target_csv)
        shutil.copy2(source_json, target_json)

        metadata = {
            "name": name,
            "source_csv": str(source_csv.relative_to(ROOT)),
            "source_json": str(source_json.relative_to(ROOT)),
            "stable_csv": str(target_csv.relative_to(ROOT)),
            "stable_json": str(target_json.relative_to(ROOT)),
            **_csv_stats(target_csv),
        }
        manifest["combined"][name] = metadata

    _write_json(STABLE_OUTPUT_DIR / "manifest.json", manifest)
    print(f"Stable outputs written to {STABLE_OUTPUT_DIR}")
    return 0


def _latest_prefix(shop_dir: Path, *, suffix: str) -> str | None:
    if not shop_dir.exists():
        return None

    prefixes: list[str] = []
    for path in shop_dir.glob(f"*{suffix}.json"):
        name = path.stem
        parts = name.split("_")
        if len(parts) < 3:
            continue
        prefixes.append(parts[0])
    return max(prefixes) if prefixes else None


def _latest_top_level_prefix(glob_pattern: str) -> str | None:
    prefixes: list[str] = []
    for path in OUTPUTS_DIR.glob(f"{glob_pattern}.json"):
        prefixes.append(path.stem.split("_", maxsplit=1)[0])
    return max(prefixes) if prefixes else None


def _csv_stats(csv_path: Path) -> dict[str, Any]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {
        "row_count": len(rows),
        "valid_count": sum(row.get("data_valid") == "True" for row in rows),
        "style_code_count": sum(bool(row.get("style_code")) for row in rows),
        "brand_present_count": sum(bool(row.get("brand_name")) for row in rows),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)


if __name__ == "__main__":
    raise SystemExit(main())
