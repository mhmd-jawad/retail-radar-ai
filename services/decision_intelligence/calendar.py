"""
Shared Lebanon retail event calendar for IE2.

This module keeps a small set of fixed-date retail windows and exposes helpers
for date-based event proximity scoring and event-aware rule logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class RetailEventWindow:
    """A named retail event window with a peak date and demand scoring curve.

    Attributes:
        name: Internal event identifier (e.g. ``"back_to_school"``).
        start_date: First day of the event window.
        peak_date: Day of maximum demand / pricing impact.
        end_date: Last day of the event window.
        peak_score: Maximum proximity score (0.0–1.0) achieved on ``peak_date``.
    """

    name: str
    start_date: date
    peak_date: date
    end_date: date
    peak_score: float

def _fixed_event_windows(year: int) -> list[RetailEventWindow]:
    """Return the fixed-date retail event windows for the given calendar year.

    Args:
        year: The calendar year to build windows for.

    Returns:
        List of :class:`RetailEventWindow` instances covering back-to-school,
        pre-holiday, and holiday-gifting periods.
    """
    return [
        RetailEventWindow(
            name="back_to_school",
            start_date=date(year, 8, 15),
            peak_date=date(year, 9, 1),
            end_date=date(year, 9, 20),
            peak_score=0.9,
        ),
        RetailEventWindow(
            name="pre_holiday",
            start_date=date(year, 11, 15),
            peak_date=date(year, 11, 28),
            end_date=date(year, 12, 5),
            peak_score=0.6,
        ),
        RetailEventWindow(
            name="holiday_gifting",
            start_date=date(year, 12, 6),
            peak_date=date(year, 12, 20),
            end_date=date(year, 12, 31),
            peak_score=0.8,
        ),
    ]


def get_retail_event_windows(year: int) -> list[RetailEventWindow]:
    """Return all retail event windows for the given year.

    Args:
        year: The calendar year.

    Returns:
        List of :class:`RetailEventWindow` objects.
    """
    return _fixed_event_windows(year)


def _score_event_window(target_date: date, event: RetailEventWindow, lookahead_days: int = 14) -> float:
    """Score how much a single event window influences ``target_date``.

    Returns a float in [0.0, 1.0] reflecting proximity to the event peak.
    The score ramps up linearly before the peak, fades after it, and applies
    a lookahead ramp for dates up to ``lookahead_days`` before the window opens.

    Args:
        target_date: The date being evaluated.
        event: The retail event window to score against.
        lookahead_days: Number of days before the window start to begin ramping.

    Returns:
        Proximity score in [0.0, 1.0].
    """
    if event.start_date <= target_date <= event.end_date:
        if target_date <= event.peak_date:
            total_days = max((event.peak_date - event.start_date).days, 1)
            progress = (target_date - event.start_date).days / total_days
            return round(0.55 + progress * (event.peak_score - 0.55), 3)

        total_days = max((event.end_date - event.peak_date).days, 1)
        fade = (target_date - event.peak_date).days / total_days
        return round(max(0.35, event.peak_score - fade * (event.peak_score - 0.35)), 3)

    if target_date < event.start_date:
        days_until = (event.start_date - target_date).days
        if days_until <= lookahead_days:
            progress = (lookahead_days - days_until) / max(lookahead_days, 1)
            return round(0.20 + progress * 0.30, 3)

    return 0.0


def get_event_proximity_score(target_date: date, lookahead_days: int = 14) -> float:
    """Return the maximum event proximity score for a given date.

    Checks both the current year and the following year so that
    year-boundary events are captured correctly.

    Args:
        target_date: The date to score.
        lookahead_days: How many days ahead of each window to start scoring.

    Returns:
        Maximum proximity score across all known event windows, in [0.0, 1.0].
    """
    windows = get_retail_event_windows(target_date.year) + get_retail_event_windows(target_date.year + 1)
    return max((_score_event_window(target_date, event, lookahead_days) for event in windows), default=0.0)


def get_active_or_upcoming_event(
    target_date: date,
    lookahead_days: int = 14,
) -> tuple[RetailEventWindow | None, int | None]:
    """Find the active or nearest upcoming event window for a given date.

    If ``target_date`` falls inside an event window the closest-to-peak
    window is returned with ``days_until = 0``. Otherwise, the nearest
    upcoming window within ``lookahead_days`` is returned.

    Args:
        target_date: The date to evaluate.
        lookahead_days: How many days ahead to look for upcoming events.

    Returns:
        A tuple of ``(event_window, days_until_start)``.
        Both values are ``None`` when no relevant event is found.
    """
    windows = get_retail_event_windows(target_date.year) + get_retail_event_windows(target_date.year + 1)

    active_events = [event for event in windows if event.start_date <= target_date <= event.end_date]
    if active_events:
        active_event = min(active_events, key=lambda event: abs((event.peak_date - target_date).days))
        return active_event, 0

    upcoming_events = []
    for event in windows:
        if target_date < event.start_date:
            days_until = (event.start_date - target_date).days
            if days_until <= lookahead_days:
                upcoming_events.append((days_until, event))

    if not upcoming_events:
        return None, None

    days_until, event = min(upcoming_events, key=lambda item: item[0])
    return event, days_until
