"""Exchange calendar integration for market holidays and trading hours.

This module provides calendar-aware functionality for different Databento datasets:
- GLBX.MDP3 (CME futures): Uses CMES calendar, has electronic trading hours
- OPRA.PILLAR (options): Uses XNYS calendar, follows NYSE schedule
- XNAS.ITCH, DBEQ.BASIC (equities): Use XNYS calendar

Key behaviors:
- CME is OPEN on most US federal holidays but with EARLY CLOSE
- NYSE/OPRA is CLOSED on federal holidays
- Both have early close days (day before July 4th, Black Friday, Christmas Eve)
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from functools import lru_cache

import exchange_calendars as xcals

logger = logging.getLogger(__name__)

# Dataset to exchange calendar mapping
DATASET_CALENDAR_MAP: dict[str, str] = {
    # CME futures - electronic trading hours, open on most holidays with early close
    "GLBX.MDP3": "CMES",
    # US options - follows NYSE schedule
    "OPRA.PILLAR": "XNYS",
    # NASDAQ equities - follows NYSE holiday schedule
    "XNAS.ITCH": "XNYS",
    # US equities
    "DBEQ.BASIC": "XNYS",
    # ICE futures
    "IFEU.IMPACT": "IEPA",
    "IFLL.IMPACT": "IEPA",
    "IFUS.IMPACT": "IEPA",
    "NDEX.IMPACT": "IEPA",
}

# Default calendar for unknown datasets (assumes US market hours)
DEFAULT_CALENDAR = "XNYS"


@lru_cache(maxsize=8)
def _get_calendar(calendar_name: str) -> xcals.ExchangeCalendar:
    """Get a cached exchange calendar instance.

    Calendar initialization is expensive (~100ms), so we cache instances.
    """
    import exchange_calendars as xcals

    return xcals.get_calendar(calendar_name)


def get_calendar_for_dataset(dataset: str) -> xcals.ExchangeCalendar:
    """Get the appropriate exchange calendar for a dataset.

    Args:
        dataset: Databento dataset name (e.g., 'GLBX.MDP3', 'OPRA.PILLAR')

    Returns:
        Exchange calendar instance for the dataset.
    """
    calendar_name = DATASET_CALENDAR_MAP.get(dataset, DEFAULT_CALENDAR)
    return _get_calendar(calendar_name)


def is_trading_day(d: date, dataset: str) -> bool:
    """Check if a date is a trading day for the given dataset.

    Args:
        d: Date to check
        dataset: Databento dataset name

    Returns:
        True if the market is open (even with early close), False if closed.
    """
    calendar = get_calendar_for_dataset(dataset)
    try:
        return calendar.is_session(d.isoformat())
    except Exception as e:
        logger.warning(
            "Calendar is_session lookup failed for %s on %s: %s. Assuming open.",
            dataset,
            d,
            e,
        )
        # Assume market is open if lookup fails (fail-safe)
        return True


def is_early_close(d: date, dataset: str) -> bool:
    """Check if a date is an early close day for the given dataset.

    Args:
        d: Date to check
        dataset: Databento dataset name

    Returns:
        True if the market closes early on this day.
    """
    calendar = get_calendar_for_dataset(dataset)
    try:
        # First check if it's a trading day at all
        if not calendar.is_session(d.isoformat()):
            return False
        # Check if in early_closes
        early_close_dates = {ec.date() for ec in calendar.early_closes}
        return d in early_close_dates
    except Exception as e:
        logger.warning(
            "Calendar early_close lookup failed for %s on %s: %s",
            dataset,
            d,
            e,
        )
        return False


def get_session_close(d: date, dataset: str) -> tuple[int, int] | None:
    """Get the session close time (UTC) for a trading day.

    Args:
        d: Date to get close time for
        dataset: Databento dataset name

    Returns:
        Tuple of (hour, minute) in UTC, or None if not a trading day.
    """
    calendar = get_calendar_for_dataset(dataset)
    try:
        if not calendar.is_session(d.isoformat()):
            return None
        close = calendar.session_close(d.isoformat())
        return (close.hour, close.minute)
    except Exception as e:
        logger.warning(
            "Calendar session_close lookup failed for %s on %s: %s",
            dataset,
            d,
            e,
        )
        return None


def iter_trading_days(start: date, end: date, dataset: str) -> Iterator[date]:
    """Iterate over trading days in a date range.

    This is the calendar-aware replacement for iter_days() that skips
    holidays and weekends based on the exchange calendar.

    Args:
        start: Start date (inclusive)
        end: End date (inclusive)
        dataset: Databento dataset name

    Yields:
        Each trading day in the range.
    """
    calendar = get_calendar_for_dataset(dataset)
    try:
        sessions = calendar.sessions_in_range(start.isoformat(), end.isoformat())
        for session in sessions:
            yield session.date()
    except Exception as e:
        logger.warning(
            "Calendar sessions_in_range failed for %s (%s to %s): %s. "
            "Falling back to all days.",
            dataset,
            start,
            end,
            e,
        )
        # Fall back to all calendar days if lookup fails
        from datetime import timedelta

        current = start
        while current <= end:
            yield current
            current += timedelta(days=1)


def get_trading_day_count(start: date, end: date, dataset: str) -> int:
    """Count trading days in a date range.

    Args:
        start: Start date (inclusive)
        end: End date (inclusive)
        dataset: Databento dataset name

    Returns:
        Number of trading days in the range.
    """
    return sum(1 for _ in iter_trading_days(start, end, dataset))


def get_next_trading_day(d: date, dataset: str) -> date:
    """Get the next trading day on or after the given date.

    Args:
        d: Starting date
        dataset: Databento dataset name

    Returns:
        The next trading day (could be the same date if it's a trading day).
    """
    calendar = get_calendar_for_dataset(dataset)
    try:
        session = calendar.date_to_session(d.isoformat(), direction="next")
        return session.date()
    except Exception as e:
        logger.warning(
            "Calendar date_to_session failed for %s on %s: %s. Returning same date.",
            dataset,
            d,
            e,
        )
        return d


def get_previous_trading_day(d: date, dataset: str) -> date:
    """Get the previous trading day on or before the given date.

    Args:
        d: Starting date
        dataset: Databento dataset name

    Returns:
        The previous trading day (could be the same date if it's a trading day).
    """
    calendar = get_calendar_for_dataset(dataset)
    try:
        session = calendar.date_to_session(d.isoformat(), direction="previous")
        return session.date()
    except Exception as e:
        logger.warning(
            "Calendar date_to_session failed for %s on %s: %s. Returning same date.",
            dataset,
            d,
            e,
        )
        return d
