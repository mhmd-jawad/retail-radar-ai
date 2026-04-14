"""Common normalization helpers for product catalog records."""

from __future__ import annotations

from datetime import datetime, timezone
import html as html_lib
import re
from typing import Iterable

MISSING_IDENTIFIER = "does_not_exist"

GENERIC_VENDOR_VALUES = {
    "",
    "kix",
    "kix lebanon",
    "shoesbullet",
    "citysport",
    "citysport lb",
    "mikesport",
    "mike sport",
    "marka store",
    "marka",
}

BRAND_ALIASES = [
    ("new balance", "New Balance"),
    ("under armour", "Under Armour"),
    ("the north face", "The North Face"),
    ("on running", "On"),
    ("on cloud", "On"),
    ("adidas", "Adidas"),
    ("nike", "Nike"),
    ("jordan", "Jordan"),
    ("puma", "Puma"),
    ("hoka", "Hoka"),
    ("asics", "ASICS"),
    ("asics", "ASICS"),
    ("reebok", "Reebok"),
    ("crocs", "Crocs"),
    ("bogner", "Bogner"),
    ("salomon", "Salomon"),
    ("converse", "Converse"),
    ("vans", "Vans"),
    ("skechers", "Skechers"),
    ("timberland", "Timberland"),
    ("trimberland", "Timberland"),
    ("balenciaga", "Balenciaga"),
    ("caterpillar", "CAT"),
    ("cat", "CAT"),
    ("ugg", "UGG"),
    ("champion", "Champion"),
    ("speedo", "Speedo"),
    ("columbia", "Columbia"),
    ("erke", "Erke"),
    ("li-ning", "Li-Ning"),
    ("lining", "Li-Ning"),
    ("tnf", "The North Face"),
    ("nb", "New Balance"),
]

STYLE_CODE_PATTERNS = [
    re.compile(r"\b\d[A-Z]{2}\d{8}\b", re.IGNORECASE),
    re.compile(r"\b[A-Z]{1,3}\d{4,6}(?:-\d{3})?\b", re.IGNORECASE),
    re.compile(r"\b[A-Z]{2}\d{3,5}[A-Z]?\b", re.IGNORECASE),
]

PRODUCT_CODE_LABEL_PATTERNS = [
    re.compile(r"(?:product|style|article|model)\s*code\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{2,})", re.IGNORECASE),
    re.compile(r"\bref(?:erence)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{2,})", re.IGNORECASE),
]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", html_lib.unescape(str(value))).strip()
    return cleaned or None


def normalize_identifier(value: object, *, missing_value: str = MISSING_IDENTIFIER) -> str:
    cleaned = clean_text(value)
    return cleaned if cleaned else missing_value


def has_real_identifier(value: object) -> bool:
    cleaned = clean_text(value)
    return bool(cleaned and cleaned.lower() != MISSING_IDENTIFIER)


def parse_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    cleaned = re.sub(r"[^\d.]", "", str(value))
    if not cleaned:
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def discount_pct(regular_price: float | None, sale_price: float | None) -> float | None:
    if regular_price is None or sale_price is None or regular_price <= 0:
        return None
    if sale_price >= regular_price:
        return None
    return round(((regular_price - sale_price) / regular_price) * 100, 2)


def unique_preserve_order(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        if not cleaned or cleaned.lower() == "default title":
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output


def infer_brand_name(*signals: object) -> str | None:
    raw_values = [clean_text(signal) or "" for signal in signals]
    for raw in raw_values:
        if raw.lower() not in GENERIC_VENDOR_VALUES:
            for alias, canonical in BRAND_ALIASES:
                if raw.lower() == alias:
                    return canonical

    haystack = " ".join(raw_values).lower()
    for alias, canonical in BRAND_ALIASES:
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", haystack):
            return canonical
    return None


def infer_gender_target(*signals: object) -> str | None:
    haystack = " ".join(clean_text(signal) or "" for signal in signals).lower()
    if re.search(r"\bunisex\b", haystack):
        return "unisex"
    if re.search(r"\b(women|womens|woman|ladies|female)\b", haystack):
        return "women"
    if re.search(r"\b(men|mens|male)\b|men's", haystack):
        return "men"
    if re.search(r"\b(girls|girl)\b", haystack):
        return "girls"
    if re.search(r"\b(boys|boy)\b", haystack):
        return "boys"
    if re.search(r"\b(kids|kid|children|junior|youth)\b", haystack):
        return "kids"
    return None


def normalize_category(*signals: object) -> str | None:
    for signal in signals:
        cleaned = clean_text(signal)
        if cleaned:
            return cleaned
    return None


def infer_style_code(*signals: object) -> str | None:
    for signal in signals:
        text = clean_text(signal)
        if not text:
            continue
        normalized = re.sub(r"[^A-Za-z0-9-]+", " ", text.upper())
        for pattern in STYLE_CODE_PATTERNS:
            for match in pattern.finditer(normalized):
                candidate = match.group(0).upper().strip("-")
                if _looks_like_style_code(candidate):
                    return candidate
    return None


def extract_product_code(*signals: object) -> str | None:
    for signal in signals:
        if signal in (None, ""):
            continue
        raw = html_lib.unescape(str(signal))
        stripped = _strip_tags(raw)
        for haystack in (raw, stripped):
            if not haystack:
                continue
            for pattern in PRODUCT_CODE_LABEL_PATTERNS:
                for match in pattern.finditer(haystack):
                    candidate = clean_text(match.group(1))
                    if not candidate:
                        continue
                    candidate = candidate.upper().strip("-")
                    if _looks_like_style_code(candidate) or _looks_like_numeric_product_code(candidate):
                        return candidate

    for signal in signals:
        text = _strip_tags(signal)
        if not text:
            continue
        for token in re.findall(r"[A-Z0-9-]{4,14}", text.upper()):
            candidate = token.strip("-")
            if _matches_style_code_pattern(candidate) or _looks_like_numeric_product_code(candidate):
                return candidate
    return None


def _looks_like_style_code(candidate: str) -> bool:
    if not candidate or candidate.isdigit():
        return False
    collapsed = candidate.replace("-", "")
    if len(collapsed) < 5 or len(collapsed) > 14:
        return False
    if not any(char.isalpha() for char in collapsed):
        return False
    if not any(char.isdigit() for char in collapsed):
        return False
    if re.fullmatch(r"[A-Z]{2}\d{2}", collapsed):
        return False
    return True


def _matches_style_code_pattern(candidate: str) -> bool:
    return any(pattern.fullmatch(candidate) for pattern in STYLE_CODE_PATTERNS) and _looks_like_style_code(candidate)


def _looks_like_numeric_product_code(candidate: str) -> bool:
    return bool(re.fullmatch(r"\d{5,10}", candidate))


def _strip_tags(value: object) -> str | None:
    if value in (None, ""):
        return None
    stripped = re.sub(r"<[^>]+>", " ", html_lib.unescape(str(value)))
    return clean_text(stripped)


def competitor_product_id(competitor_name: str, source_id: object) -> str:
    return f"{competitor_name}:{clean_text(source_id) or 'unknown'}"
