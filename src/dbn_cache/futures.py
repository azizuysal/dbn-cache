"""Futures contract date calculation.

This module provides utilities for parsing futures contract symbols and
calculating appropriate date ranges for downloading data.

Supported products:
- Equity index: ES, NQ, RTY, YM, EMD, MES, MNQ, M2K, MYM, NKD, NIY
- Treasuries: ZB, ZN, ZF, ZT, UB
- Metals: GC, SI, HG, PL, PA

Example:
    >>> from dbn_cache.futures import get_contract_dates
    >>> start, end = get_contract_dates("NQH25")
    >>> print(f"Download from {start} to {end}")
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from exchange_calendars import ExchangeCalendar

from .calendar import get_calendar_for_dataset

MONTH_CODES: dict[str, int] = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}

# Quarterly months for standard futures contracts
QUARTERLY_MONTHS = (3, 6, 9, 12)  # H, M, U, Z

# Supported product roots by expiration rule
EQUITY_INDEX_FUTURES: frozenset[str] = frozenset(
    {
        "ES",  # E-mini S&P 500
        "NQ",  # E-mini NASDAQ-100
        "RTY",  # E-mini Russell 2000
        "YM",  # E-mini Dow ($5)
        "EMD",  # E-mini S&P MidCap 400
        "MES",  # Micro E-mini S&P 500
        "MNQ",  # Micro E-mini NASDAQ-100
        "M2K",  # Micro E-mini Russell 2000
        "MYM",  # Micro E-mini Dow
        "NKD",  # Nikkei 225 (Dollar-denominated)
        "NIY",  # Nikkei 225 (Yen-denominated)
    }
)

TREASURY_FUTURES: frozenset[str] = frozenset(
    {
        "ZB",  # 30-Year T-Bond
        "ZN",  # 10-Year T-Note
        "ZF",  # 5-Year T-Note
        "ZT",  # 2-Year T-Note
        "UB",  # Ultra T-Bond
    }
)

METAL_FUTURES: frozenset[str] = frozenset(
    {
        "GC",  # Gold
        "SI",  # Silver
        "HG",  # Copper
        "PL",  # Platinum
        "PA",  # Palladium
    }
)

ALL_SUPPORTED_ROOTS: frozenset[str] = (
    EQUITY_INDEX_FUTURES | TREASURY_FUTURES | METAL_FUTURES
)

# Pattern for specific futures contracts: ROOT + MONTH_CODE + YEAR
# Examples: NQH25, ESZ24, MESH25, M2KU24 (2-digit year required)
CONTRACT_PATTERN = re.compile(
    r"^([A-Z0-9]{1,4})([FGHJKMNQUVXZ])(\d{2})$", re.IGNORECASE
)


def parse_contract_symbol(symbol: str) -> tuple[str, int, int]:
    """Parse a futures contract symbol into its components.

    Symbol format: ROOT + MONTH_CODE + YEAR (e.g., NQH25, ESZ24, MESH25)

    Requires 2-digit year for clarity:
        - 25 → 2025
        - 16 → 2016

    Args:
        symbol: Futures contract symbol (e.g., "NQH25", "ESZ24", "MESH25")

    Returns:
        Tuple of (root, month, year) where:
        - root: Product root in uppercase (e.g., "NQ", "ES", "MES")
        - month: Contract month as integer (1-12)
        - year: Full year (e.g., 2025)

    Raises:
        ValueError: If symbol doesn't match futures contract pattern,
            has an invalid month code, or uses single-digit year.

    Example:
        >>> parse_contract_symbol("NQH25")
        ('NQ', 3, 2025)
        >>> parse_contract_symbol("NQH16")
        ('NQ', 3, 2016)
    """
    match = CONTRACT_PATTERN.match(symbol)
    if not match:
        msg = (
            f"Could not parse '{symbol}' as a futures contract. "
            f"Expected format: ROOT + MONTH_CODE + 2-DIGIT_YEAR (e.g., NQH25, ESZ24)"
        )
        raise ValueError(msg)

    root = match.group(1).upper()
    month_code = match.group(2).upper()
    year_str = match.group(3)

    if month_code not in MONTH_CODES:
        msg = f"Invalid month code '{month_code}' in symbol '{symbol}'"
        raise ValueError(msg)

    month = MONTH_CODES[month_code]

    # 2-digit year → 20XX
    year = 2000 + int(year_str)

    return root, month, year


def to_databento_symbol(symbol: str) -> str:
    """Convert a futures contract symbol to Databento API format.

    Databento uses single-digit years internally. The date range passed
    to the API disambiguates the decade (e.g., NQH6 with dates in 2016
    vs dates in 2026).

    This is used internally for API calls. Users should always use
    2-digit years (NQH25, not NQH5).

    Args:
        symbol: Futures contract symbol with 2-digit year (e.g., "NQH25")

    Returns:
        Symbol in Databento format with single-digit year (e.g., "NQH5")

    Example:
        >>> to_databento_symbol("NQH25")  # 2025 → 5
        'NQH5'
        >>> to_databento_symbol("NQH16")  # 2016 → 6
        'NQH6'
    """
    root, month, year = parse_contract_symbol(symbol)
    month_code = next(k for k, v in MONTH_CODES.items() if v == month)
    year_digit = year % 10  # Last digit only
    return f"{root}{month_code}{year_digit}"


def is_supported_contract(symbol: str) -> bool:
    """Check if a symbol is a supported futures contract for auto-detection.

    Args:
        symbol: Symbol to check

    Returns:
        True if the symbol is a recognized futures contract with a supported
        product root, False otherwise.

    Example:
        >>> is_supported_contract("NQH25")
        True
        >>> is_supported_contract("VXH25")
        False
        >>> is_supported_contract("AAPL")
        False
    """
    try:
        root, _, _ = parse_contract_symbol(symbol)
        return root in ALL_SUPPORTED_ROOTS
    except ValueError:
        return False


def is_supported_root(symbol: str) -> bool:
    """Check if a symbol is a supported futures root (not a specific contract).

    Args:
        symbol: Symbol to check (e.g., "NQ", "ES", "GC")

    Returns:
        True if the symbol is a recognized futures root.

    Example:
        >>> is_supported_root("NQ")
        True
        >>> is_supported_root("NQH25")  # Specific contract, not root
        False
        >>> is_supported_root("VX")  # Not supported
        False
    """
    return symbol.upper() in ALL_SUPPORTED_ROOTS


# Reverse mapping: month number to code
MONTH_TO_CODE: dict[int, str] = {v: k for k, v in MONTH_CODES.items()}


def generate_quarterly_contracts(
    root: str,
    from_year: int,
    to_year: int | None = None,
) -> list[str]:
    """Generate all quarterly contract symbols for a root over a year range.

    Quarterly months are March (H), June (M), September (U), December (Z).

    Args:
        root: Futures root symbol (e.g., "NQ", "ES", "GC")
        from_year: Starting year (inclusive)
        to_year: Ending year (inclusive). If None, uses current year.

    Returns:
        List of contract symbols in chronological order.

    Raises:
        ValueError: If root is not a supported futures root.

    Example:
        >>> generate_quarterly_contracts("NQ", 2024, 2025)
        ['NQH24', 'NQM24', 'NQU24', 'NQZ24', 'NQH25', 'NQM25', 'NQU25', 'NQZ25']
    """
    root = root.upper()
    if root not in ALL_SUPPORTED_ROOTS:
        supported = sorted(ALL_SUPPORTED_ROOTS)
        msg = f"'{root}' is not a supported futures root. Supported: {supported}"
        raise ValueError(msg)

    if to_year is None:
        from datetime import date as date_type

        to_year = date_type.today().year

    contracts: list[str] = []
    for year in range(from_year, to_year + 1):
        year_suffix = year % 100  # 2024 -> 24
        for month in QUARTERLY_MONTHS:
            month_code = MONTH_TO_CODE[month]
            contracts.append(f"{root}{month_code}{year_suffix:02d}")

    return contracts


def _get_cme_calendar() -> ExchangeCalendar:
    """Get the CME calendar for expiration calculations."""
    return get_calendar_for_dataset("GLBX.MDP3")


def _third_friday(month: int, year: int) -> date:
    """Calculate the 3rd Friday of a month, adjusted for holidays.

    If the 3rd Friday is not a trading day (holiday), returns the
    previous trading day.

    Args:
        month: Month (1-12)
        year: Full year

    Returns:
        Expiration date (3rd Friday or previous trading day if holiday)
    """
    # Find the first day of the month
    first_day = date(year, month, 1)

    # Find the first Friday
    # weekday() returns 0=Monday, 4=Friday
    days_until_friday = (4 - first_day.weekday()) % 7
    first_friday = first_day + timedelta(days=days_until_friday)

    # Third Friday is 2 weeks after first Friday
    third_friday = first_friday + timedelta(weeks=2)

    # Adjust for holidays using CME calendar
    calendar = _get_cme_calendar()
    if not calendar.is_session(third_friday.isoformat()):
        # Find previous trading day
        prev_session = calendar.date_to_session(
            third_friday.isoformat(), direction="previous"
        )
        return prev_session.date()

    return third_friday


def _last_business_day(month: int, year: int) -> date:
    """Get the last business day of a month."""
    import calendar as cal

    last_day = cal.monthrange(year, month)[1]
    last_date = date(year, month, last_day)

    exchange_cal = _get_cme_calendar()
    if not exchange_cal.is_session(last_date.isoformat()):
        prev_session = exchange_cal.date_to_session(
            last_date.isoformat(), direction="previous"
        )
        return prev_session.date()

    return last_date


def _business_days_before(d: date, days: int) -> date:
    """Count back N business days from a date.

    Args:
        d: Starting date
        days: Number of business days to count back

    Returns:
        Date that is N business days before d
    """
    calendar = _get_cme_calendar()
    current = d
    counted = 0

    while counted < days:
        current = current - timedelta(days=1)
        if calendar.is_session(current.isoformat()):
            counted += 1

    return current


def _treasury_expiration(month: int, year: int) -> date:
    """Calculate treasury futures expiration.

    Rule: 7 business days before the last business day of the contract month.

    Args:
        month: Contract month (1-12)
        year: Full year

    Returns:
        Expiration date
    """
    last_bday = _last_business_day(month, year)
    return _business_days_before(last_bday, 7)


def _metals_expiration(month: int, year: int) -> date:
    """Calculate metals futures expiration.

    Rule: 3rd last business day of the contract month.

    Args:
        month: Contract month (1-12)
        year: Full year

    Returns:
        Expiration date
    """
    last_bday = _last_business_day(month, year)
    return _business_days_before(last_bday, 2)  # 3rd last = 2 days before last


def get_expiration_date(root: str, month: int, year: int) -> date:
    """Calculate the expiration date for a futures contract.

    Args:
        root: Product root (e.g., "NQ", "ZN", "GC")
        month: Contract month (1-12)
        year: Full year

    Returns:
        Expiration date

    Raises:
        ValueError: If root is not a supported product
    """
    if root in EQUITY_INDEX_FUTURES:
        return _third_friday(month, year)
    elif root in TREASURY_FUTURES:
        return _treasury_expiration(month, year)
    elif root in METAL_FUTURES:
        return _metals_expiration(month, year)
    else:
        msg = f"Unsupported product: {root}"
        raise ValueError(msg)


def _previous_quarterly_month(month: int, year: int) -> tuple[int, int]:
    """Get the previous quarterly contract month.

    Quarterly months are March (H), June (M), September (U), December (Z).

    Args:
        month: Current contract month (1-12)
        year: Current contract year

    Returns:
        Tuple of (previous_month, previous_year)

    Example:
        >>> _previous_quarterly_month(3, 2025)  # H25 -> Z24
        (12, 2024)
        >>> _previous_quarterly_month(6, 2025)  # M25 -> H25
        (3, 2025)
    """
    # Find the previous quarterly month
    quarter_months = list(QUARTERLY_MONTHS)
    if month in quarter_months:
        idx = quarter_months.index(month)
        if idx == 0:
            # March -> previous December
            return 12, year - 1
        else:
            return quarter_months[idx - 1], year
    else:
        # Non-quarterly month: find the most recent quarterly month before it
        for q in reversed(quarter_months):
            if q < month:
                return q, year
        # If month is before March, previous is December of last year
        return 12, year - 1


def get_contract_dates(
    symbol: str,
    rollover_days: int = 14,
) -> tuple[date, date]:
    """Get the recommended date range for downloading a futures contract.

    Calculates:
    - End date: Contract expiration
    - Start date: Previous contract expiration minus rollover buffer

    This provides data from the rollover period (when the contract becomes
    front month) through expiration.

    Symbol format: ROOT + MONTH_CODE + 2-DIGIT_YEAR (e.g., NQH25, ESZ24)

    Args:
        symbol: Futures contract symbol with 2-digit year (e.g., "NQH25", "ESZ24")
        rollover_days: Number of days before front-month to start.
            Default 14 covers the typical roll period.

    Returns:
        Tuple of (start_date, end_date)

    Raises:
        ValueError: If symbol cannot be parsed or product is not supported

    Example:
        >>> start, end = get_contract_dates("NQH25")
        >>> print(f"Download from {start} to {end}")
        Download from 2024-12-06 to 2025-03-21

        >>> start, end = get_contract_dates("NQH16")  # Historical
        >>> print(f"Download from {start} to {end}")
        Download from 2015-12-04 to 2016-03-18
    """
    root, month, year = parse_contract_symbol(symbol)

    if root not in ALL_SUPPORTED_ROOTS:
        msg = (
            f"Cannot auto-detect dates for {symbol}. "
            f"{root} is not a supported product. "
            f"Please provide --start and --end explicitly."
        )
        raise ValueError(msg)

    # End date is this contract's expiration
    end = get_expiration_date(root, month, year)

    # Start date is previous contract's expiration minus rollover buffer
    prev_month, prev_year = _previous_quarterly_month(month, year)
    prev_expiry = get_expiration_date(root, prev_month, prev_year)
    start = prev_expiry - timedelta(days=rollover_days)

    return start, end
