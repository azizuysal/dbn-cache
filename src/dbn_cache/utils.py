from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CachedDataInfo, DateRange

TICK_SCHEMAS = frozenset(
    {"trades", "mbp-1", "mbp-10", "mbo", "tbbo", "bbo-1s", "bbo-1m"}
)
OHLCV_SCHEMAS = frozenset(
    {"ohlcv-1s", "ohlcv-1m", "ohlcv-1h", "ohlcv-1d", "statistics"}
)


def utc_today() -> date:
    """Get today's date in UTC timezone.

    Uses UTC instead of local time for consistency across different timezones.
    This ensures the same date is used regardless of where the code runs.
    """
    return datetime.now(UTC).date()


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol for filesystem paths (ES.c.0 → ES_c_0)."""
    return symbol.replace(".", "_")


def detect_stype(symbol: str) -> str:
    """Detect symbol type from symbol format.

    Returns:
        'continuous' for ES.c.0, ES.v.0, ES.n.0
        'parent' for ES.FUT, SPX.OPT, BTC.SPOT
        'raw_symbol' for ESZ24, AAPL
    """
    if re.match(r"^[A-Z0-9]+\.[cvn]\.\d+$", symbol):
        return "continuous"
    if re.match(r"^[A-Z0-9]+\.(FUT|OPT|SPOT)$", symbol):
        return "parent"
    return "raw_symbol"


def is_tick_schema(schema: str) -> bool:
    """Check if schema is tick-level (partitioned daily)."""
    return schema in TICK_SCHEMAS


def get_default_cache_dir() -> Path:
    """Get default cache directory.

    Returns:
        - Windows: %LOCALAPPDATA%\\databento
        - Unix/Mac: ~/.databento
    """
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "databento"
        return Path.home() / "AppData" / "Local" / "databento"
    return Path.home() / ".databento"


def iter_months(start: date, end: date) -> Iterator[tuple[int, int]]:
    """Iterate over (year, month) tuples in date range."""
    current = date(start.year, start.month, 1)
    end_month = date(end.year, end.month, 1)
    while current <= end_month:
        yield current.year, current.month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


def iter_days(start: date, end: date) -> Iterator[date]:
    """Iterate over dates in range (inclusive)."""
    from datetime import timedelta

    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def get_partition_path(
    base_path: Path,
    schema: str,
    year: int,
    month: int,
    day: int | None = None,
) -> Path:
    """Get path to a partition file.

    For OHLCV schemas: base_path/{year}/{month:02d}.parquet
    For tick schemas: base_path/{year}/{month:02d}/{day:02d}.parquet
    """
    if is_tick_schema(schema):
        if day is None:
            msg = "Day required for tick schemas"
            raise ValueError(msg)
        return base_path / str(year) / f"{month:02d}" / f"{day:02d}.parquet"
    return base_path / str(year) / f"{month:02d}.parquet"


def month_start_end(year: int, month: int) -> tuple[date, date]:
    """Get first and last day of a month."""
    import calendar

    first = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = date(year, month, last_day)
    return first, last


def merge_date_ranges(
    ranges: list[tuple[date, date]],
) -> list[tuple[date, date]]:
    """Merge overlapping or adjacent date ranges."""
    if not ranges:
        return []
    from datetime import timedelta

    sorted_ranges = sorted(ranges, key=lambda r: r[0])
    merged: list[tuple[date, date]] = []
    for start, end in sorted_ranges:
        if merged and start <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def find_missing_date_ranges(
    start: date,
    end: date,
    cached_ranges: list[tuple[date, date]],
) -> list[tuple[date, date]]:
    """Find date ranges not covered by cached_ranges."""
    if not cached_ranges:
        return [(start, end)]

    from datetime import timedelta

    missing: list[tuple[date, date]] = []
    current = start

    for r_start, r_end in sorted(cached_ranges, key=lambda x: x[0]):
        if current < r_start:
            gap_end = min(r_start - timedelta(days=1), end)
            if gap_end >= current:
                missing.append((current, gap_end))
        current = max(current, r_end + timedelta(days=1))
        if current > end:
            break

    if current <= end:
        missing.append((current, end))

    return missing


def has_lookahead_bias(symbol: str) -> bool:
    """Check if symbol uses volume/OI-based rolls which have look-ahead bias.

    Returns True for .v. (volume) and .n. (OI) continuous futures.
    """
    return ".v." in symbol or ".n." in symbol


def parse_date(value: str) -> date:
    """Parse date string (YYYY-MM-DD) to date object."""
    return date.fromisoformat(value)


def format_date_ranges(ranges: list[DateRange]) -> str:
    """Format date ranges for display."""
    return ", ".join(f"{r.start} to {r.end}" for r in ranges)


def filter_by_symbol_prefix(
    items: list[CachedDataInfo], symbol: str
) -> list[CachedDataInfo]:
    """Filter cached data items by case-insensitive symbol prefix match."""
    symbol_lower = symbol.lower()
    return [item for item in items if item.symbol.lower().startswith(symbol_lower)]
