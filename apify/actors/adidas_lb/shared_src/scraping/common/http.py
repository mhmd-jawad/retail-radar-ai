"""HTTP helpers for polite, repeatable background scraping."""

from __future__ import annotations

import time
from typing import Any

import requests


DEFAULT_USER_AGENT = (
    "StylePulseAI-MarketIntelligence/0.2 "
    "(background competitor ingestion; contact: engineering@stylepulse.local)"
)


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def get_text(
    session: requests.Session,
    url: str,
    *,
    timeout: int = 30,
    retries: int = 2,
    sleep_seconds: float = 0.4,
) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(sleep_seconds * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error


def get_json(
    session: requests.Session,
    url: str,
    *,
    timeout: int = 30,
    retries: int = 2,
    sleep_seconds: float = 0.4,
) -> dict[str, Any]:
    text = get_text(
        session,
        url,
        timeout=timeout,
        retries=retries,
        sleep_seconds=sleep_seconds,
    )
    try:
        return requests.models.complexjson.loads(text)
    except ValueError as exc:
        raise RuntimeError(f"Expected JSON from {url}") from exc

