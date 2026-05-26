"""Prometheus metrics for the EEP service."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from prometheus_client import Counter, Histogram, make_asgi_app
from starlette.responses import Response

try:  # Optional locally, installed in the EEP Docker image.
    from prometheus_fastapi_instrumentator import Instrumentator
except ImportError:  # pragma: no cover - exercised when dependency is unavailable.
    Instrumentator = None  # type: ignore[assignment]


HTTP_REQUESTS_TOTAL = Counter(
    "eep_http_requests_total",
    "Total EEP HTTP requests.",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "eep_http_request_duration_seconds",
    "EEP HTTP request latency in seconds.",
    ["method", "path"],
)
RECOMMENDATIONS_TOTAL = Counter(
    "eep_recommendations_total",
    "EEP recommendations returned by IE2 decision.",
    ["endpoint", "recommendation"],
)
COMPETITOR_MATCHES_TOTAL = Counter(
    "eep_competitor_matches_total",
    "Competitor matching outcomes observed before IE2 validation.",
    ["match_type"],
)
SCRAPER_INGEST_TOTAL = Counter(
    "eep_scraper_ingest_total",
    "Apify scraper ingest attempts handled by EEP.",
    ["source", "status"],
)


def configure_metrics(app: Any) -> None:
    """Expose /metrics and record basic HTTP metrics.

    The Instrumentator package is used when available. A lightweight
    prometheus-client fallback keeps local tests/dev usable before dependencies
    are installed.
    """
    if Instrumentator is not None:
        Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(
            app,
            endpoint="/metrics",
            include_in_schema=False,
        )
    else:
        app.mount("/metrics", make_asgi_app())

    @app.middleware("http")
    async def _metrics_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path.startswith("/metrics"):
            return await call_next(request)

        started = time.perf_counter()
        status_code = "500"
        route_path = _route_path(request)
        try:
            response = await call_next(request)
            status_code = str(response.status_code)
            return response
        finally:
            route_path = _route_path(request, default=route_path)
            HTTP_REQUESTS_TOTAL.labels(request.method, route_path, status_code).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(request.method, route_path).observe(
                time.perf_counter() - started
            )


def observe_recommendation(endpoint: str, recommendation: str | None) -> None:
    decision = str(recommendation or "UNKNOWN").upper()
    RECOMMENDATIONS_TOTAL.labels(endpoint, decision).inc()


def observe_competitor_match(competitor_signals: Any) -> None:
    match_type = "missing"
    if isinstance(competitor_signals, dict):
        fallback_used = bool(competitor_signals.get("fallback_used"))
        competitor_count = int(float(competitor_signals.get("num_competitors_tracked") or 0))
        if fallback_used and competitor_count == 0:
            match_type = "no_match"
        else:
            match_type = str(competitor_signals.get("match_type") or "matched_unknown")
    COMPETITOR_MATCHES_TOTAL.labels(match_type).inc()


def observe_scraper_ingest(status: str, source: str = "apify") -> None:
    SCRAPER_INGEST_TOTAL.labels(source, status).inc()


def _route_path(request: Request, default: str | None = None) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path or default or request.url.path)
