from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest

from dbn_cache.cache import DataCache
from dbn_cache.exceptions import CacheMissError
from dbn_cache.models import DateRange, SymbolMeta


class TestDataCacheInit:
    def test_default_cache_dir(self) -> None:
        cache = DataCache()
        assert cache.cache_dir == Path.home() / ".databento"

    def test_custom_cache_dir(self, tmp_path: Path) -> None:
        cache = DataCache(cache_dir=tmp_path)
        assert cache.cache_dir == tmp_path

    def test_env_cache_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABENTO_CACHE_DIR", str(tmp_path))
        cache = DataCache()
        assert cache.cache_dir == tmp_path


class TestDataCacheGet:
    def test_get_not_cached(self, tmp_path: Path) -> None:
        cache = DataCache(cache_dir=tmp_path)
        with pytest.raises(CacheMissError):
            cache.get("ES.c.0", "ohlcv-1m", date(2024, 1, 1), date(2024, 3, 31))

    def test_get_partial_cache(self, tmp_path: Path) -> None:
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "ohlcv-1m"
        base_path.mkdir(parents=True)
        (base_path / "2024").mkdir()
        df = pl.DataFrame({"ts": [1, 2, 3], "price": [100.0, 101.0, 102.0]})
        df.write_parquet(base_path / "2024" / "01.parquet")

        meta_path = base_path / "meta.json"
        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="ohlcv-1m",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31))],
            updated_at=datetime.now(),
        )
        import json

        with meta_path.open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, default=str)

        with pytest.raises(CacheMissError):
            cache.get("ES.c.0", "ohlcv-1m", date(2024, 1, 1), date(2024, 3, 31))

    def test_get_cached(self, tmp_path: Path) -> None:
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "ohlcv-1m"
        base_path.mkdir(parents=True)
        (base_path / "2024").mkdir()
        df = pl.DataFrame({"ts": [1, 2, 3], "price": [100.0, 101.0, 102.0]})
        df.write_parquet(base_path / "2024" / "01.parquet")

        meta_path = base_path / "meta.json"
        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="ohlcv-1m",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31))],
            updated_at=datetime.now(),
        )
        import json

        with meta_path.open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, default=str)

        data = cache.get("ES.c.0", "ohlcv-1m", date(2024, 1, 1), date(2024, 1, 31))
        assert len(data.paths) == 1


class TestDataCacheInfo:
    def test_info_not_cached(self, tmp_path: Path) -> None:
        cache = DataCache(cache_dir=tmp_path)
        info = cache.info("ES.c.0", "ohlcv-1m")
        assert info is None

    def test_info_cached(self, tmp_path: Path) -> None:
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "ohlcv-1m"
        base_path.mkdir(parents=True)
        (base_path / "2024").mkdir()
        df = pl.DataFrame({"ts": [1, 2, 3]})
        df.write_parquet(base_path / "2024" / "01.parquet")

        meta_path = base_path / "meta.json"
        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="ohlcv-1m",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31))],
            updated_at=datetime.now(),
        )
        import json

        with meta_path.open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, default=str)

        info = cache.info("ES.c.0", "ohlcv-1m")
        assert info is not None
        assert info.symbol == "ES.c.0"
        assert info.size_bytes > 0


class TestDataCacheListCached:
    def test_list_empty(self, tmp_path: Path) -> None:
        cache = DataCache(cache_dir=tmp_path)
        items = cache.list_cached()
        assert items == []

    def test_list_with_data(self, tmp_path: Path) -> None:
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "ohlcv-1m"
        base_path.mkdir(parents=True)

        meta_path = base_path / "meta.json"
        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="ohlcv-1m",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31))],
            updated_at=datetime.now(),
        )
        import json

        with meta_path.open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, default=str)

        items = cache.list_cached()
        assert len(items) == 1
        assert items[0].symbol == "ES.c.0"


class TestDataCacheUpdate:
    def test_update_no_cached_data(self, tmp_path: Path) -> None:
        cache = DataCache(cache_dir=tmp_path)
        with pytest.raises(CacheMissError, match="No cached data"):
            cache.update("ES.c.0", "ohlcv-1m")

    def test_update_already_up_to_date(self, tmp_path: Path) -> None:
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "ohlcv-1m"
        base_path.mkdir(parents=True)
        (base_path / "2024").mkdir()
        df = pl.DataFrame({"ts": [1, 2, 3]})
        df.write_parquet(base_path / "2024" / "12.parquet")

        meta_path = base_path / "meta.json"
        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="ohlcv-1m",
            ranges=[DateRange(start=date(2024, 1, 1), end=date.today())],
            updated_at=datetime.now(),
        )
        import json

        with meta_path.open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, default=str)

        result = cache.update("ES.c.0", "ohlcv-1m")
        assert result is None

    def test_update_expired_futures_contract(self, tmp_path: Path) -> None:
        """Expired futures contracts should not be updated past expiration."""
        cache = DataCache(cache_dir=tmp_path)

        # NQH24 expired on 2024-03-15 (3rd Friday of March 2024)
        base_path = tmp_path / "GLBX.MDP3" / "NQH24" / "ohlcv-1d"
        base_path.mkdir(parents=True)
        (base_path / "2024").mkdir()
        df = pl.DataFrame({"ts": [1, 2, 3]})
        df.write_parquet(base_path / "2024" / "03.parquet")

        meta_path = base_path / "meta.json"
        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="NQH24",
            stype="raw_symbol",
            schema="ohlcv-1d",
            # Cached through expiration
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 3, 15))],
            updated_at=datetime.now(),
        )
        import json

        with meta_path.open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, default=str)

        # Should return None since contract is expired and fully cached
        result = cache.update("NQH24", "ohlcv-1d")
        assert result is None


class TestGetUpdateRangeExpiredContracts:
    """Test get_update_range respects futures contract expiration."""

    def test_expired_contract_returns_none(self, tmp_path: Path) -> None:
        """Fully cached expired contracts should not need updates."""
        from dbn_cache.models import CachedDataInfo

        cache = DataCache(cache_dir=tmp_path)

        # NQH24 expired on 2024-03-15
        cached_info = CachedDataInfo(
            dataset="GLBX.MDP3",
            symbol="NQH24",
            schema="ohlcv-1d",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 3, 15))],
            size_bytes=1000,
        )

        update_range = cache.get_update_range(cached_info)
        assert update_range is None

    def test_partial_contract_caps_at_expiration(self, tmp_path: Path) -> None:
        """Contracts cached before expiration should cap update at expiration."""
        from dbn_cache.models import CachedDataInfo

        cache = DataCache(cache_dir=tmp_path)

        # NQH24 expired on 2024-03-15, but only cached through March 10
        cached_info = CachedDataInfo(
            dataset="GLBX.MDP3",
            symbol="NQH24",
            schema="ohlcv-1d",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 3, 10))],
            size_bytes=1000,
        )

        update_range = cache.get_update_range(cached_info)
        assert update_range is not None
        start, end = update_range
        assert start == date(2024, 3, 11)
        assert end == date(2024, 3, 15)  # Capped at expiration

    def test_continuous_futures_not_capped(self, tmp_path: Path) -> None:
        """Continuous futures contracts should not have expiration caps."""
        from dbn_cache.models import CachedDataInfo

        cache = DataCache(cache_dir=tmp_path)

        cached_info = CachedDataInfo(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            schema="ohlcv-1d",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 3, 10))],
            size_bytes=1000,
        )

        update_range = cache.get_update_range(cached_info)
        assert update_range is not None
        _start, end = update_range
        # End should be yesterday, not capped at any expiration
        assert end > date(2024, 3, 15)


class TestDataCacheUpdateAll:
    def test_update_all_empty_cache(self, tmp_path: Path) -> None:
        cache = DataCache(cache_dir=tmp_path)
        result = cache.update_all()
        assert result.updated_count == 0
        assert result.up_to_date_count == 0
        assert result.error_count == 0

    def test_update_all_already_up_to_date(self, tmp_path: Path) -> None:
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "ohlcv-1m"
        base_path.mkdir(parents=True)
        (base_path / "2024").mkdir()
        df = pl.DataFrame({"ts": [1, 2, 3]})
        df.write_parquet(base_path / "2024" / "12.parquet")

        meta_path = base_path / "meta.json"
        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="ohlcv-1m",
            ranges=[DateRange(start=date(2024, 1, 1), end=date.today())],
            updated_at=datetime.now(),
        )
        import json

        with meta_path.open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, default=str)

        result = cache.update_all()
        assert result.updated_count == 0
        assert result.up_to_date_count == 1
        assert result.error_count == 0
        assert not result.has_errors


class TestValidateMetadata:
    """Test that metadata validation detects and fixes mismatches."""

    def test_fragmented_ranges_detected(self, tmp_path: Path) -> None:
        """Fragmented ranges should be detected by validate_metadata."""
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "ohlcv-1m"
        base_path.mkdir(parents=True)
        (base_path / "2024").mkdir()

        # Create parquet file with datetime timestamps spanning Jan-Mar
        df = pl.DataFrame(
            {
                "ts_event": pl.Series(
                    [
                        datetime(2024, 1, 15, 10, 0),
                        datetime(2024, 2, 15, 10, 0),
                        datetime(2024, 3, 15, 10, 0),
                    ]
                ).cast(pl.Datetime("ns"))
            }
        )
        df.write_parquet(base_path / "2024" / "01.parquet")

        # Create metadata with FRAGMENTED ranges
        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="ohlcv-1m",
            ranges=[
                DateRange(start=date(2024, 1, 15), end=date(2024, 1, 31)),
                DateRange(start=date(2024, 2, 1), end=date(2024, 2, 29)),
                DateRange(start=date(2024, 3, 1), end=date(2024, 3, 15)),
            ],
            updated_at=datetime.now(),
        )
        import json

        meta_path = base_path / "meta.json"
        with meta_path.open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, default=str)

        # Loading metadata should NOT auto-fix (returns fragmented as-is)
        info = cache.info("ES.c.0", "ohlcv-1m")
        assert info is not None
        assert len(info.ranges) == 3

        # validate_metadata should detect the mismatch
        issues = cache.validate_metadata()
        assert len(issues) == 1
        assert issues[0][1] == "ES.c.0"

        # validate_metadata with fix=True should consolidate
        cache.validate_metadata(fix=True)
        info = cache.info("ES.c.0", "ohlcv-1m")
        assert info is not None
        assert len(info.ranges) == 1
        assert info.ranges[0].start == date(2024, 1, 15)
        assert info.ranges[0].end == date(2024, 3, 15)

    def test_single_range_not_modified(self, tmp_path: Path) -> None:
        """A single valid range should not be modified."""
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "ohlcv-1m"
        base_path.mkdir(parents=True)
        (base_path / "2024").mkdir()

        df = pl.DataFrame(
            {
                "ts_event": pl.Series(
                    [datetime(2024, 1, 1, 10, 0), datetime(2024, 3, 31, 10, 0)]
                ).cast(pl.Datetime("ns"))
            }
        )
        df.write_parquet(base_path / "2024" / "01.parquet")

        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="ohlcv-1m",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 3, 31))],
            updated_at=datetime.now(),
        )
        import json

        meta_path = base_path / "meta.json"
        with meta_path.open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, default=str)

        info = cache.info("ES.c.0", "ohlcv-1m")

        assert info is not None
        assert len(info.ranges) == 1
        assert info.ranges[0].start == date(2024, 1, 1)
        assert info.ranges[0].end == date(2024, 3, 31)


class TestRepairOrphanedMetadata:
    """Test rebuilding metadata for parquet files without meta.json."""

    def test_repair_orphaned_parquet(self, tmp_path: Path) -> None:
        """Parquet files without meta.json should have metadata rebuilt."""
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "ohlcv-1m"
        base_path.mkdir(parents=True)
        (base_path / "2024").mkdir()

        # Create parquet file WITHOUT meta.json
        df = pl.DataFrame(
            {
                "ts_event": pl.Series(
                    [datetime(2024, 1, 5, 10, 0), datetime(2024, 2, 20, 10, 0)]
                ).cast(pl.Datetime("ns"))
            }
        )
        df.write_parquet(base_path / "2024" / "01.parquet")

        # Verify no metadata exists
        assert not (base_path / "meta.json").exists()

        # Repair should rebuild it
        repaired = cache.repair_metadata()

        assert len(repaired) == 1
        assert repaired[0] == ("GLBX.MDP3", "ES.c.0", "ohlcv-1m")

        # Verify metadata now exists
        assert (base_path / "meta.json").exists()

        # Verify metadata is correct
        info = cache.info("ES.c.0", "ohlcv-1m")
        assert info is not None
        assert len(info.ranges) == 1
        assert info.ranges[0].start == date(2024, 1, 5)
        assert info.ranges[0].end == date(2024, 2, 20)

    def test_repair_no_orphans(self, tmp_path: Path) -> None:
        """When all metadata exists, repair returns empty list."""
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "ohlcv-1m"
        base_path.mkdir(parents=True)
        (base_path / "2024").mkdir()

        df = pl.DataFrame({"ts_event": [1, 2, 3]})
        df.write_parquet(base_path / "2024" / "01.parquet")

        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="ohlcv-1m",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31))],
            updated_at=datetime.now(),
        )
        import json

        with (base_path / "meta.json").open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, default=str)

        repaired = cache.repair_metadata()
        assert repaired == []

    def test_repair_empty_directory(self, tmp_path: Path) -> None:
        """Directory with no parquet files should not be repaired."""
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "ohlcv-1m"
        base_path.mkdir(parents=True)

        repaired = cache.repair_metadata()
        assert repaired == []


class TestOHLCVPartitionDateExpansion:
    """Test that OHLCV updates expand to include existing cached data."""

    def test_ohlcv_update_includes_cached_data_in_download(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mid-month update should download from start of cached data."""
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "ohlcv-1m"
        base_path.mkdir(parents=True)
        (base_path / "2024").mkdir()

        # Create existing parquet with data for Jan 1-15
        df = pl.DataFrame(
            {
                "ts_event": pl.Series(
                    [datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 15, 10, 0)]
                ).cast(pl.Datetime("ns"))
            }
        )
        df.write_parquet(base_path / "2024" / "01.parquet")

        # Create metadata showing Jan 1-15 cached
        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="ohlcv-1m",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 1, 15))],
            updated_at=datetime.now(),
        )
        import json

        with (base_path / "meta.json").open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, default=str)

        # Track what dates are requested for download
        download_calls: list[tuple[date, date]] = []

        def mock_download_partition(
            symbol: str,
            schema: str,
            start: date,
            end: date,
            dataset: str,
            dest: Path,
        ) -> None:
            download_calls.append((start, end))
            # Write a fake parquet file
            df = pl.DataFrame(
                {
                    "ts_event": pl.Series(
                        [datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 20, 10, 0)]
                    ).cast(pl.Datetime("ns"))
                }
            )
            df.write_parquet(dest)

        monkeypatch.setattr(cache, "_download_partition", mock_download_partition)

        # Request update for Jan 16-20 (extending cached data)
        cache.download("ES.c.0", "ohlcv-1m", date(2024, 1, 16), date(2024, 1, 20))

        # Should have made 1 download call
        assert len(download_calls) == 1

        # The download should include existing cached data (Jan 1) to avoid data loss
        dl_start, dl_end = download_calls[0]
        assert dl_start == date(2024, 1, 1), "Should download from cached start"
        assert dl_end == date(2024, 1, 20), "Should download to requested end"

    def test_tick_schema_no_expansion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tick schemas (daily partitions) should not expand to include cached."""
        cache = DataCache(cache_dir=tmp_path)

        base_path = tmp_path / "GLBX.MDP3" / "ES_c_0" / "trades"
        base_path.mkdir(parents=True)
        (base_path / "2024" / "01").mkdir(parents=True)

        # Create metadata showing Jan 1-15 cached
        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="trades",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 1, 15))],
            updated_at=datetime.now(),
        )
        import json

        with (base_path / "meta.json").open("w") as f:
            json.dump(meta.model_dump(by_alias=True), f, default=str)

        # Create existing parquet files for Jan 1-15
        for day in range(1, 16):
            df = pl.DataFrame({"ts_event": [1, 2, 3]})
            df.write_parquet(base_path / "2024" / "01" / f"{day:02d}.parquet")

        # Track what dates are requested
        download_calls: list[tuple[date, date]] = []

        def mock_download_partition(
            symbol: str,
            schema: str,
            start: date,
            end: date,
            dataset: str,
            dest: Path,
        ) -> None:
            download_calls.append((start, end))
            df = pl.DataFrame({"ts_event": [1, 2, 3]})
            df.write_parquet(dest)

        monkeypatch.setattr(cache, "_download_partition", mock_download_partition)

        # Request Jan 16-17 (new days, not overlapping cached)
        cache.download("ES.c.0", "trades", date(2024, 1, 16), date(2024, 1, 17))

        # Should have 2 download calls (one per day)
        assert len(download_calls) == 2

        # Each should be exactly the requested day (no expansion)
        assert download_calls[0] == (date(2024, 1, 16), date(2024, 1, 16))
        assert download_calls[1] == (date(2024, 1, 17), date(2024, 1, 17))


class TestCalendarDateMerging:
    """Test that calendar-based dates merge correctly."""

    def test_adjacent_months_merge(self) -> None:
        """Adjacent month boundaries should merge (June 30 + July 1)."""
        from dbn_cache.utils import merge_date_ranges

        # Simulate two months downloaded sequentially
        ranges = [
            (date(2024, 6, 1), date(2024, 6, 30)),  # June
            (date(2024, 7, 1), date(2024, 7, 31)),  # July
        ]

        merged = merge_date_ranges(ranges)

        assert len(merged) == 1
        assert merged[0] == (date(2024, 6, 1), date(2024, 7, 31))

    def test_real_gap_does_not_merge(self) -> None:
        """Real gaps (e.g., missing weeks) should not merge."""
        from dbn_cache.utils import merge_date_ranges

        # Jan 1-15 and Feb 1-28 with gap
        ranges = [
            (date(2024, 1, 1), date(2024, 1, 15)),
            (date(2024, 2, 1), date(2024, 2, 28)),
        ]

        merged = merge_date_ranges(ranges)

        assert len(merged) == 2
        assert merged[0] == (date(2024, 1, 1), date(2024, 1, 15))
        assert merged[1] == (date(2024, 2, 1), date(2024, 2, 28))
