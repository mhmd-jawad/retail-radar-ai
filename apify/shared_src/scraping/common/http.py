"""HTTP helpers for polite, repeatable background scraping."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
from typing import Any

import requests


DEFAULT_USER_AGENT = (
    "StylePulseAI-MarketIntelligence/0.2 "
    "(background competitor ingestion; contact: engineering@stylepulse.local)"
)
RATE_LIMIT_STATUS_CODE = 429
RETRYABLE_STATUS_CODES = {RATE_LIMIT_STATUS_CODE, 500, 502, 503, 504}


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
    retries: int = 6,
    sleep_seconds: float = 1.0,
    max_sleep_seconds: float = 60.0,
) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries and _should_retry(exc):
                time.sleep(
                    _retry_delay(
                        exc,
                        attempt=attempt,
                        sleep_seconds=sleep_seconds,
                        max_sleep_seconds=max_sleep_seconds,
                    )
                )
    raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error


def _should_retry(exc: requests.RequestException) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return status_code is None or status_code in RETRYABLE_STATUS_CODES


def _retry_delay(
    exc: requests.RequestException,
    *,
    attempt: int,
    sleep_seconds: float,
    max_sleep_seconds: float,
) -> float:
    response = getattr(exc, "response", None)
    retry_after = _retry_after_delay(response)
    if retry_after is not None:
        return min(max(retry_after, sleep_seconds), max_sleep_seconds)

    status_code = getattr(response, "status_code", None)
    base_sleep = max(sleep_seconds, 10.0) if status_code == RATE_LIMIT_STATUS_CODE else sleep_seconds
    return min(base_sleep * (2**attempt), max_sleep_seconds)


def _retry_after_delay(response: requests.Response | None) -> float | None:
    if response is None:
        return None

    value = response.headers.get("Retry-After")
    if not value:
        return None

    try:
        return max(float(value), 0.0)
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max((retry_at - datetime.now(timezone.utc)).total_seconds(), 0.0)


def get_json(
    session: requests.Session,
    url: str,
    *,
    timeout: int = 30,
    retries: int = 6,
    sleep_seconds: float = 1.0,
    max_sleep_seconds: float = 60.0,
) -> dict[str, Any]:
    text = get_text(
        session,
        url,
        timeout=timeout,
        retries=retries,
        sleep_seconds=sleep_seconds,
        max_sleep_seconds=max_sleep_seconds,
    )
    try:
        return requests.models.complexjson.loads(text)
    except ValueError as exc:
        raise RuntimeError(f"Expected JSON from {url}") from exc
