import json
import logging
import os
import shutil
import tempfile
import warnings
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
from filelock import FileLock

from .client import DatabentoClient
from .exceptions import CacheMissError, DownloadCancelledError, EmptyDataError
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
    SymbolMeta,
)
from .utils import (
    detect_stype,
    find_missing_date_ranges,
    get_default_cache_dir,
    get_partition_path,
    is_tick_schema,
    iter_days,
    iter_months,
    merge_date_ranges,
    month_start_end,
    normalize_symbol,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)


def _parse_quality_warnings(
    caught_warnings: list[warnings.WarningMessage],
) -> list[DataQualityIssue]:
    """Parse databento warnings into DataQualityIssue objects."""
    issues: list[DataQualityIssue] = []
    seen_dates: set[date] = set()

    for w in caught_warnings:
        msg = str(w.message)
        if "reduced quality:" in msg:
            parts = msg.split("reduced quality:")[1]
            date_section = parts.split(".")[0].strip()
            for entry in date_section.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                date_str = entry.split(" ")[0]
                issue_type = "degraded"
                if "(" in entry and ")" in entry:
                    issue_type = entry.split("(")[1].split(")")[0]
                try:
                    d = date.fromisoformat(date_str)
                    if d not in seen_dates:
                        issues.append(
                            DataQualityIssue(date=d, issue_type=issue_type, message=msg)
                        )
                        seen_dates.add(d)
                except ValueError:
                    pass

    return sorted(issues, key=lambda i: i.date)


class DataCache:
    """Cache for Databento historical market data."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        client: DatabentoClient | None = None,
    ) -> None:
        """Initialize cache.

        Args:
            cache_dir: Cache directory. Defaults to ~/.databento or DATABENTO_CACHE_DIR.
            client: DatabentoClient instance. Created on demand if not provided.
        """
        if cache_dir is None:
            env_dir = os.environ.get("DATABENTO_CACHE_DIR")
            cache_dir = Path(env_dir) if env_dir else get_default_cache_dir()
        self._cache_dir = cache_dir
        self._client = client

    @property
    def cache_dir(self) -> Path:
        """Get cache directory."""
        return self._cache_dir

    def _get_client(self) -> DatabentoClient:
        """Get or create client."""
        if self._client is None:
            self._client = DatabentoClient()
        return self._client

    def _get_symbol_path(self, dataset: str, symbol: str, schema: str) -> Path:
        """Get path to symbol/schema cache directory."""
        return self._cache_dir / dataset / normalize_symbol(symbol) / schema

    def _get_meta_path(self, dataset: str, symbol: str, schema: str) -> Path:
        """Get path to metadata file."""
        return self._get_symbol_path(dataset, symbol, schema) / "meta.json"

    def _get_lock_path(self, dataset: str, symbol: str, schema: str) -> Path:
        """Get path to lock file."""
        return self._get_symbol_path(dataset, symbol, schema) / ".lock"

    @contextmanager
    def _lock(
        self, dataset: str, symbol: str, schema: str, timeout: float = 300
    ) -> "Iterator[None]":
        """Acquire file lock for symbol/schema."""
        lock_path = self._get_lock_path(dataset, symbol, schema)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(lock_path, timeout=timeout)
        with lock:
            yield

    def _load_meta(self, dataset: str, symbol: str, schema: str) -> SymbolMeta | None:
        """Load metadata from cache."""
        meta_path = self._get_meta_path(dataset, symbol, schema)
        if not meta_path.exists():
            return None
        with meta_path.open() as f:
            data = json.load(f)
        return SymbolMeta.model_validate(data)

    def _save_meta(self, meta: SymbolMeta) -> None:
        """Save metadata to cache."""
        meta_path = self._get_meta_path(meta.dataset, meta.symbol, meta.schema_)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with meta_path.open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, indent=2, default=str)

    def _merge_ranges(self, ranges: list[DateRange]) -> list[DateRange]:
        """Merge overlapping or adjacent date ranges."""
        tuples = [(r.start, r.end) for r in ranges]
        merged = merge_date_ranges(tuples)
        return [DateRange(start=s, end=e) for s, e in merged]

    def _find_missing_ranges(
        self, start: date, end: date, cached_ranges: list[DateRange]
    ) -> list[DateRange]:
        """Find date ranges not covered by cached_ranges."""
        tuples = [(r.start, r.end) for r in cached_ranges]
        missing = find_missing_date_ranges(start, end, tuples)
        return [DateRange(start=s, end=e) for s, e in missing]

    def _download_partition(
        self,
        symbol: str,
        schema: str,
        start: date,
        end: date,
        dataset: str,
        dest_path: Path,
    ) -> None:
        """Download data for a partition and save to dest_path."""
        import polars as pl

        client = self._get_client()
        data = client.fetch(
            symbol=symbol,
            schema=schema,
            start=start,
            end=end,
            dataset=dataset,
        )
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        df = pl.from_pandas(data.to_df())
        df.write_parquet(dest_path)

    def _get_cached_files(
        self, dataset: str, symbol: str, schema: str, start: date, end: date
    ) -> list[Path]:
        """Get list of cached parquet files for date range."""
        base_path = self._get_symbol_path(dataset, symbol, schema)
        files: list[Path] = []

        if is_tick_schema(schema):
            for d in iter_days(start, end):
                path = get_partition_path(base_path, schema, d.year, d.month, d.day)
                if path.exists():
                    files.append(path)
        else:
            for year, month in iter_months(start, end):
                path = get_partition_path(base_path, schema, year, month)
                if path.exists():
                    files.append(path)

        return files

    def _count_partitions_in_range(
        self,
        schema: str,
        start: date,
        end: date,
    ) -> int:
        """Count total partitions in a date range."""
        count = 0
        if is_tick_schema(schema):
            for _ in iter_days(start, end):
                count += 1
        else:
            for _ in iter_months(start, end):
                count += 1
        return count

    def _get_missing_partitions(
        self,
        dataset: str,
        symbol: str,
        schema: str,
        start: date,
        end: date,
    ) -> list[DateRange]:
        """Find partitions that are missing actual files on disk.

        Returns date ranges for partitions where files don't exist,
        regardless of what metadata says.
        """
        base_path = self._get_symbol_path(dataset, symbol, schema)
        missing: list[DateRange] = []

        if is_tick_schema(schema):
            for d in iter_days(start, end):
                path = get_partition_path(base_path, schema, d.year, d.month, d.day)
                if not path.exists():
                    missing.append(DateRange(start=d, end=d))
        else:
            for year, month in iter_months(start, end):
                path = get_partition_path(base_path, schema, year, month)
                if not path.exists():
                    m_start, m_end = month_start_end(year, month)
                    clamped_start = max(m_start, start)
                    clamped_end = min(m_end, end)
                    missing.append(DateRange(start=clamped_start, end=clamped_end))

        return self._merge_ranges(missing) if missing else []

    def check_cache(
        self,
        symbol: str,
        schema: str,
        start: date,
        end: date,
        dataset: str = "GLBX.MDP3",
        verify_files: bool = True,
    ) -> CacheCheckResult:
        """Check cache status for a date range.

        Args:
            symbol: Symbol to check
            schema: Data schema
            start: Start date (inclusive)
            end: End date (inclusive)
            dataset: Databento dataset
            verify_files: If True, verify actual files exist (not just metadata)

        Returns:
            CacheCheckResult with status and details about cached/missing data.
        """
        meta = self._load_meta(dataset, symbol, schema)
        cached_ranges = list(meta.ranges) if meta else []
        missing_from_meta = self._find_missing_ranges(start, end, cached_ranges)

        if verify_files:
            missing_files = self._get_missing_partitions(
                dataset, symbol, schema, start, end
            )
            all_missing = missing_from_meta + missing_files
            missing_ranges = self._merge_ranges(all_missing) if all_missing else []
        else:
            missing_ranges = missing_from_meta

        total_partitions = self._count_partitions_in_range(schema, start, end)

        if not missing_ranges:
            return CacheCheckResult(
                status=CacheStatus.COMPLETE,
                cached_ranges=cached_ranges,
                missing_ranges=[],
                cached_partitions=total_partitions,
                missing_partitions=0,
            )

        missing_partitions = sum(
            self._count_partitions_in_range(schema, r.start, r.end)
            for r in missing_ranges
        )
        cached_partitions = total_partitions - missing_partitions
        status = CacheStatus.EMPTY if cached_partitions == 0 else CacheStatus.PARTIAL

        return CacheCheckResult(
            status=status,
            cached_ranges=cached_ranges,
            missing_ranges=missing_ranges,
            cached_partitions=cached_partitions,
            missing_partitions=missing_partitions,
        )

    def clear_cache(
        self,
        symbol: str,
        schema: str,
        start: date,
        end: date,
        dataset: str = "GLBX.MDP3",
    ) -> int:
        """Clear cached data for a date range.

        Args:
            symbol: Symbol to clear
            schema: Data schema
            start: Start date (inclusive)
            end: End date (inclusive)
            dataset: Databento dataset

        Returns:
            Number of partition files deleted.
        """
        base_path = self._get_symbol_path(dataset, symbol, schema)
        deleted = 0

        with self._lock(dataset, symbol, schema):
            if is_tick_schema(schema):
                for d in iter_days(start, end):
                    path = get_partition_path(base_path, schema, d.year, d.month, d.day)
                    if path.exists():
                        path.unlink()
                        deleted += 1
            else:
                for year, month in iter_months(start, end):
                    path = get_partition_path(base_path, schema, year, month)
                    if path.exists():
                        path.unlink()
                        deleted += 1

            meta = self._load_meta(dataset, symbol, schema)
            if meta:
                remaining_ranges: list[DateRange] = []
                for r in meta.ranges:
                    if r.end < start or r.start > end:
                        remaining_ranges.append(r)
                    elif r.start < start and r.end > end:
                        remaining_ranges.append(DateRange(start=r.start, end=start))
                        remaining_ranges.append(DateRange(start=end, end=r.end))
                    elif r.start < start:
                        remaining_ranges.append(DateRange(start=r.start, end=start))
                    elif r.end > end:
                        remaining_ranges.append(DateRange(start=end, end=r.end))

                if remaining_ranges:
                    meta.ranges = self._merge_ranges(remaining_ranges)
                    self._save_meta(meta)
                else:
                    meta_path = self._get_meta_path(dataset, symbol, schema)
                    if meta_path.exists():
                        meta_path.unlink()

        return deleted

    def _count_partitions_to_download(
        self,
        schema: str,
        missing: list[DateRange],
        base_path: Path,
    ) -> tuple[int, list[tuple[PartitionInfo, Path, date, date]]]:
        """Count partitions that need downloading and build download list.

        Returns:
            Tuple of (total count, list of partition download info).
        """
        partitions: list[tuple[PartitionInfo, Path, date, date]] = []

        for gap in missing:
            if is_tick_schema(schema):
                for d in iter_days(gap.start, gap.end):
                    dest = get_partition_path(base_path, schema, d.year, d.month, d.day)
                    if not dest.exists():
                        info = PartitionInfo(year=d.year, month=d.month, day=d.day)
                        partitions.append((info, dest, d, d))
            else:
                for year, month in iter_months(gap.start, gap.end):
                    dest = get_partition_path(base_path, schema, year, month)
                    if not dest.exists():
                        m_start, m_end = month_start_end(year, month)
                        dl_start = max(m_start, gap.start)
                        dl_end = min(m_end, gap.end)
                        info = PartitionInfo(year=year, month=month)
                        partitions.append((info, dest, dl_start, dl_end))

        return len(partitions), partitions

    def _save_incremental_meta(
        self,
        dataset: str,
        symbol: str,
        schema: str,
        cached_ranges: list[DateRange],
    ) -> None:
        """Save metadata with current progress."""
        new_meta = SymbolMeta(
            dataset=dataset,
            symbol=symbol,
            stype=detect_stype(symbol),
            schema=schema,
            ranges=self._merge_ranges(cached_ranges),
            updated_at=datetime.now(),
        )
        self._save_meta(new_meta)

    def download(
        self,
        symbol: str,
        schema: str,
        start: date,
        end: date,
        dataset: str = "GLBX.MDP3",
        on_progress: "Callable[[DownloadProgress], None] | None" = None,
        cancelled: "Callable[[], bool] | None" = None,
    ) -> CachedData:
        """Download data and cache it.

        Args:
            symbol: Symbol to download (e.g., 'ES.c.0', 'ESZ24')
            schema: Data schema (e.g., 'ohlcv-1m', 'trades')
            start: Start date (inclusive)
            end: End date (inclusive)
            dataset: Databento dataset
            on_progress: Optional callback for progress updates
            cancelled: Optional callable that returns True if download should stop

        Returns:
            CachedData wrapper for the downloaded files.

        Raises:
            DownloadCancelledError: If download was cancelled via the cancelled callback
        """
        if ".v." in symbol or ".n." in symbol:
            logger.warning(
                "Symbol %s uses volume/OI-based rolls which have look-ahead bias. "
                "Use calendar rolls (.c.) for backtesting.",
                symbol,
            )

        base_path = self._get_symbol_path(dataset, symbol, schema)

        with self._lock(dataset, symbol, schema):
            meta = self._load_meta(dataset, symbol, schema)
            cached_ranges = list(meta.ranges) if meta else []
            missing_from_meta = self._find_missing_ranges(start, end, cached_ranges)

            missing_files = self._get_missing_partitions(
                dataset, symbol, schema, start, end
            )
            all_missing = missing_from_meta + missing_files
            missing = self._merge_ranges(all_missing) if all_missing else []

            if not missing:
                files = self._get_cached_files(dataset, symbol, schema, start, end)
                return CachedData(files)

            total, partitions = self._count_partitions_to_download(
                schema, missing, base_path
            )

            if total == 0:
                files = self._get_cached_files(dataset, symbol, schema, start, end)
                return CachedData(files)

            completed_ranges: list[DateRange] = list(cached_ranges)

            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")
                warnings.filterwarnings("ignore", category=ResourceWarning)

                try:
                    for current, (partition_info, dest, dl_start, dl_end) in enumerate(
                        partitions, start=1
                    ):
                        if on_progress:
                            on_progress(
                                DownloadProgress(
                                    status=DownloadStatus.DOWNLOADING,
                                    partition=partition_info,
                                    current=current,
                                    total=total,
                                )
                            )

                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=".parquet"
                        ) as tmp:
                            tmp_path = Path(tmp.name)
                        try:
                            self._download_partition(
                                symbol, schema, dl_start, dl_end, dataset, tmp_path
                            )
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(tmp_path, dest)
                        except Exception:
                            tmp_path.unlink(missing_ok=True)
                            raise

                        completed_ranges.append(DateRange(start=dl_start, end=dl_end))
                        self._save_incremental_meta(
                            dataset, symbol, schema, completed_ranges
                        )

                        if on_progress:
                            on_progress(
                                DownloadProgress(
                                    status=DownloadStatus.COMPLETED,
                                    partition=partition_info,
                                    current=current,
                                    total=total,
                                )
                            )

                        if cancelled and cancelled():
                            raise DownloadCancelledError(current, total)

                finally:
                    issues = _parse_quality_warnings(list(caught_warnings))
                    if issues:
                        self.add_quality_issues(symbol, schema, issues, dataset)

        files = self._get_cached_files(dataset, symbol, schema, start, end)

        # Check if downloaded files have actual data (not just empty parquet schema)
        total_rows = sum(
            pl.scan_parquet(f).select(pl.len()).collect().item() for f in files
        )
        if total_rows == 0:
            # Clean up empty files and metadata
            for f in files:
                f.unlink(missing_ok=True)
            meta_path = self._get_meta_path(dataset, symbol, schema)
            meta_path.unlink(missing_ok=True)
            raise EmptyDataError(symbol, dataset)

        return CachedData(files)

    def get(
        self,
        symbol: str,
        schema: str,
        start: date,
        end: date,
        dataset: str = "GLBX.MDP3",
    ) -> CachedData:
        """Get data from cache.

        Args:
            symbol: Symbol to get
            schema: Data schema
            start: Start date
            end: End date
            dataset: Databento dataset

        Returns:
            CachedData wrapper.

        Raises:
            CacheMissError: If data is not fully cached or files are missing.
        """
        check = self.check_cache(symbol, schema, start, end, dataset, verify_files=True)
        if check.status != CacheStatus.COMPLETE:
            if check.status == CacheStatus.EMPTY:
                msg = f"No cached data for {symbol}/{schema}"
            else:
                msg = f"Missing data for {symbol}/{schema}: {check.missing_ranges}"
            raise CacheMissError(msg)

        files = self._get_cached_files(dataset, symbol, schema, start, end)
        return CachedData(files)

    def ensure(
        self,
        symbol: str,
        schema: str,
        start: date,
        end: date,
        dataset: str = "GLBX.MDP3",
    ) -> CachedData:
        """Ensure data is cached, downloading if needed.

        Args:
            symbol: Symbol to get
            schema: Data schema
            start: Start date
            end: End date
            dataset: Databento dataset

        Returns:
            CachedData wrapper.
        """
        try:
            return self.get(symbol, schema, start, end, dataset)
        except CacheMissError:
            return self.download(symbol, schema, start, end, dataset)

    def list_cached(self, dataset: str | None = None) -> list[CachedDataInfo]:
        """List all cached data.

        Args:
            dataset: Filter by dataset. If None, list all.

        Returns:
            List of CachedDataInfo.
        """
        results: list[CachedDataInfo] = []

        if dataset:
            datasets = [dataset]
        else:
            if not self._cache_dir.exists():
                return []
            datasets = [d.name for d in self._cache_dir.iterdir() if d.is_dir()]

        for ds in datasets:
            ds_path = self._cache_dir / ds
            if not ds_path.exists():
                continue
            for symbol_dir in ds_path.iterdir():
                if not symbol_dir.is_dir():
                    continue
                for schema_dir in symbol_dir.iterdir():
                    if not schema_dir.is_dir():
                        continue
                    meta = self._load_meta(ds, symbol_dir.name, schema_dir.name)
                    if meta:
                        size = sum(
                            f.stat().st_size
                            for f in schema_dir.rglob("*.parquet")
                            if f.is_file()
                        )
                        results.append(
                            CachedDataInfo(
                                dataset=ds,
                                symbol=meta.symbol,
                                schema=meta.schema_,
                                ranges=meta.ranges,
                                size_bytes=size,
                            )
                        )

        return results

    def info(
        self, symbol: str, schema: str, dataset: str = "GLBX.MDP3"
    ) -> CachedDataInfo | None:
        """Get info about cached data for a symbol/schema.

        Returns:
            CachedDataInfo or None if not cached.
        """
        meta = self._load_meta(dataset, symbol, schema)
        if meta is None:
            return None

        base_path = self._get_symbol_path(dataset, symbol, schema)
        size = sum(
            f.stat().st_size for f in base_path.rglob("*.parquet") if f.is_file()
        )

        return CachedDataInfo(
            dataset=dataset,
            symbol=symbol,
            schema=schema,
            ranges=meta.ranges,
            size_bytes=size,
        )

    def add_quality_issues(
        self,
        symbol: str,
        schema: str,
        issues: list[DataQualityIssue],
        dataset: str = "GLBX.MDP3",
    ) -> None:
        """Add data quality issues to metadata.

        Args:
            symbol: Symbol
            schema: Data schema
            issues: List of quality issues to add
            dataset: Databento dataset
        """
        if not issues:
            return

        with self._lock(dataset, symbol, schema):
            meta = self._load_meta(dataset, symbol, schema)
            if meta is None:
                return

            existing_dates = {i.date for i in meta.quality_issues}
            for issue in issues:
                if issue.date not in existing_dates:
                    meta.quality_issues.append(issue)
                    existing_dates.add(issue.date)

            meta.quality_issues.sort(key=lambda i: i.date)
            self._save_meta(meta)

    def get_quality_issues(
        self,
        symbol: str,
        schema: str,
        dataset: str = "GLBX.MDP3",
        start: date | None = None,
        end: date | None = None,
    ) -> list[DataQualityIssue]:
        """Get data quality issues for a symbol.

        Args:
            symbol: Symbol
            schema: Data schema
            dataset: Databento dataset
            start: Optional start date filter
            end: Optional end date filter

        Returns:
            List of quality issues, optionally filtered by date range.
        """
        meta = self._load_meta(dataset, symbol, schema)
        if meta is None:
            return []

        issues = meta.quality_issues
        if start is not None:
            issues = [i for i in issues if i.date >= start]
        if end is not None:
            issues = [i for i in issues if i.date <= end]

        return issues
