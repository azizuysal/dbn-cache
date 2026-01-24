"""Databento data cache utility.

Uses lazy imports to avoid loading heavy dependencies (polars, pandas,
exchange_calendars, databento) until they're actually needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cache import DataCache
    from .client import DatabentoClient
    from .exceptions import (
        CacheMissError,
        DownloadCancelledError,
        EmptyDataError,
        MissingAPIKeyError,
        PartialCacheError,
    )
    from .futures import (
        generate_quarterly_contracts,
        get_contract_dates,
        get_expiration_date,
        is_supported_contract,
        is_supported_root,
        parse_contract_symbol,
        to_databento_symbol,
    )
    from .models import (
        CacheCheckResult,
        CachedData,
        CachedDataInfo,
        CacheStatus,
        DataQualityIssue,
        DateRange,
        DownloadProgress,
        DownloadStatus,
        PartitionInfo,
        UpdateAllResult,
    )


__all__ = [
    "CachedData",
    "CachedDataInfo",
    "CacheCheckResult",
    "CacheMissError",
    "CacheStatus",
    "DatabentoClient",
    "DataCache",
    "DataQualityIssue",
    "DateRange",
    "DownloadCancelledError",
    "DownloadProgress",
    "DownloadStatus",
    "EmptyDataError",
    "generate_quarterly_contracts",
    "get_contract_dates",
    "get_expiration_date",
    "is_supported_contract",
    "is_supported_root",
    "MissingAPIKeyError",
    "parse_contract_symbol",
    "PartialCacheError",
    "PartitionInfo",
    "to_databento_symbol",
    "UpdateAllResult",
]


def __getattr__(name: str):
    """Lazy import public API members."""
    if name == "DataCache":
        from .cache import DataCache

        return DataCache
    if name == "DatabentoClient":
        from .client import DatabentoClient

        return DatabentoClient
    if name in (
        "CacheMissError",
        "DownloadCancelledError",
        "EmptyDataError",
        "MissingAPIKeyError",
        "PartialCacheError",
    ):
        from . import exceptions

        return getattr(exceptions, name)
    if name in (
        "generate_quarterly_contracts",
        "get_contract_dates",
        "get_expiration_date",
        "is_supported_contract",
        "is_supported_root",
        "parse_contract_symbol",
        "to_databento_symbol",
    ):
        from . import futures

        return getattr(futures, name)
    if name in (
        "CacheCheckResult",
        "CachedData",
        "CachedDataInfo",
        "CacheStatus",
        "DataQualityIssue",
        "DateRange",
        "DownloadProgress",
        "DownloadStatus",
        "PartitionInfo",
        "UpdateAllResult",
    ):
        from . import models

        return getattr(models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
