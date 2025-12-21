from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum, auto
from pathlib import Path

import pandas as pd
import polars as pl
from pydantic import BaseModel, Field


class DownloadStatus(Enum):
    """Status of a partition download."""

    DOWNLOADING = auto()
    COMPLETED = auto()


class CacheStatus(Enum):
    """Status of cache for a requested date range."""

    EMPTY = auto()
    PARTIAL = auto()
    COMPLETE = auto()


@dataclass
class CacheCheckResult:
    """Result of checking cache status for a date range."""

    status: CacheStatus
    cached_ranges: list["DateRange"]
    missing_ranges: list["DateRange"]
    cached_partitions: int
    missing_partitions: int

    @property
    def total_partitions(self) -> int:
        """Total partitions in the requested range."""
        return self.cached_partitions + self.missing_partitions


@dataclass
class PartitionInfo:
    """Information about a single partition."""

    year: int
    month: int
    day: int | None = None

    @property
    def label(self) -> str:
        """Human-readable label for this partition."""
        if self.day is not None:
            return f"{self.year}-{self.month:02d}-{self.day:02d}"
        return f"{self.year}-{self.month:02d}"


@dataclass
class DownloadProgress:
    """Progress update yielded during download."""

    status: DownloadStatus
    partition: PartitionInfo
    current: int
    total: int


class DateRange(BaseModel):
    """A date range (inclusive on both ends)."""

    start: date
    end: date


class ContractSpecs(BaseModel):
    """Contract specifications for futures."""

    multiplier: float | None = None
    tick_size: float | None = None
    currency: str | None = None


class DataQualityIssue(BaseModel):
    """A data quality issue for a specific date."""

    date: date
    issue_type: str
    message: str | None = None


class SymbolMeta(BaseModel):
    """Metadata for a cached symbol/schema combination."""

    dataset: str
    symbol: str
    stype: str
    schema_: str = Field(alias="schema")
    ranges: list[DateRange]
    updated_at: datetime
    cache_version: int = 1
    contract_specs: ContractSpecs | None = None
    quality_issues: list[DataQualityIssue] = []

    model_config = {"populate_by_name": True}


class CachedDataInfo(BaseModel):
    """Summary info about cached data."""

    dataset: str
    symbol: str
    schema_: str = Field(alias="schema")
    ranges: list[DateRange]
    size_bytes: int

    model_config = {"populate_by_name": True}


class CachedData:
    """Wrapper for cached parquet files with multi-library access."""

    def __init__(self, paths: list[Path]) -> None:
        self._paths = sorted(paths)

    @property
    def paths(self) -> list[Path]:
        """Get paths to cached parquet files."""
        return self._paths

    def to_polars(self) -> pl.LazyFrame:
        """Load data as Polars LazyFrame."""
        if not self._paths:
            return pl.LazyFrame()
        return pl.scan_parquet(self._paths)

    def to_pandas(self) -> pd.DataFrame:
        """Load data as Pandas DataFrame."""
        if not self._paths:
            return pd.DataFrame()
        lf = self.to_polars()
        return lf.collect().to_pandas()

    def __repr__(self) -> str:
        return f"CachedData(paths={len(self._paths)} files)"
