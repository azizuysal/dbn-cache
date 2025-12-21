import json
import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from filelock import FileLock

from .client import DatabentoClient
from .exceptions import CacheMissError
from .models import CachedData, CachedDataInfo, DateRange, SymbolMeta
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
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


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

    def download(
        self,
        symbol: str,
        schema: str,
        start: date,
        end: date,
        dataset: str = "GLBX.MDP3",
    ) -> CachedData:
        """Download data and cache it.

        Args:
            symbol: Symbol to download (e.g., 'ES.c.0', 'ESZ24')
            schema: Data schema (e.g., 'ohlcv-1m', 'trades')
            start: Start date (inclusive)
            end: End date (inclusive)
            dataset: Databento dataset

        Returns:
            CachedData wrapper for the downloaded files.
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
            cached_ranges = meta.ranges if meta else []
            missing = self._find_missing_ranges(start, end, cached_ranges)

            if not missing:
                files = self._get_cached_files(dataset, symbol, schema, start, end)
                return CachedData(files)

            for gap in missing:
                if is_tick_schema(schema):
                    for d in iter_days(gap.start, gap.end):
                        dest = get_partition_path(
                            base_path, schema, d.year, d.month, d.day
                        )
                        if not dest.exists():
                            with tempfile.NamedTemporaryFile(
                                delete=False, suffix=".parquet"
                            ) as tmp:
                                tmp_path = Path(tmp.name)
                            try:
                                self._download_partition(
                                    symbol, schema, d, d, dataset, tmp_path
                                )
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                shutil.move(tmp_path, dest)
                            except Exception:
                                tmp_path.unlink(missing_ok=True)
                                raise
                else:
                    for year, month in iter_months(gap.start, gap.end):
                        dest = get_partition_path(base_path, schema, year, month)
                        if not dest.exists():
                            month_start, month_end = month_start_end(year, month)
                            dl_start = max(month_start, gap.start)
                            dl_end = min(month_end, gap.end)
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

                cached_ranges.append(gap)

            new_meta = SymbolMeta(
                dataset=dataset,
                symbol=symbol,
                stype=detect_stype(symbol),
                schema=schema,
                ranges=self._merge_ranges(cached_ranges),
                updated_at=datetime.now(),
            )
            self._save_meta(new_meta)

        files = self._get_cached_files(dataset, symbol, schema, start, end)
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
            CacheMissError: If data is not fully cached.
        """
        meta = self._load_meta(dataset, symbol, schema)
        if meta is None:
            msg = f"No cached data for {symbol}/{schema}"
            raise CacheMissError(msg)

        missing = self._find_missing_ranges(start, end, meta.ranges)
        if missing:
            msg = f"Missing data for {symbol}/{schema}: {missing}"
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
