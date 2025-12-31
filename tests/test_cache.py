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
