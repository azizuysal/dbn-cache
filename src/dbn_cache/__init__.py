"""Databento data cache utility."""

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
