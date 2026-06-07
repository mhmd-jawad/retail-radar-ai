"""Output helpers for scraper runs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import SCRAPED_PRODUCT_FIELDS, ScrapedProductRecord


def write_records(records: list[ScrapedProductRecord], output_dir: Path, stem: str) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    csv_path = output_dir / f"{stem}.csv"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump([record.to_dict() for record in records], handle, indent=2, ensure_ascii=True)

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCRAPED_PRODUCT_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())

    return {"json": json_path, "csv": csv_path}

