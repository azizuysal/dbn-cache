from datetime import date, datetime
from pathlib import Path

import polars as pl

from databento_cache.models import (
    CachedData,
    CachedDataInfo,
    ContractSpecs,
    DateRange,
    SymbolMeta,
)


class TestDateRange:
    def test_create(self) -> None:
        dr = DateRange(start=date(2024, 1, 1), end=date(2024, 12, 31))
        assert dr.start == date(2024, 1, 1)
        assert dr.end == date(2024, 12, 31)


class TestContractSpecs:
    def test_create_full(self) -> None:
        specs = ContractSpecs(multiplier=50.0, tick_size=0.25, currency="USD")
        assert specs.multiplier == 50.0
        assert specs.tick_size == 0.25
        assert specs.currency == "USD"

    def test_create_partial(self) -> None:
        specs = ContractSpecs(multiplier=50.0)
        assert specs.multiplier == 50.0
        assert specs.tick_size is None
        assert specs.currency is None


class TestSymbolMeta:
    def test_create(self) -> None:
        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="ohlcv-1m",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 6, 30))],
            updated_at=datetime(2024, 12, 21),
        )
        assert meta.dataset == "GLBX.MDP3"
        assert meta.symbol == "ES.c.0"
        assert meta.schema_ == "ohlcv-1m"

    def test_serialization(self) -> None:
        meta = SymbolMeta(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            stype="continuous",
            schema="ohlcv-1m",
            ranges=[],
            updated_at=datetime(2024, 12, 21),
        )
        data = meta.model_dump(by_alias=True)
        assert "schema" in data
        assert "schema_" not in data


class TestCachedDataInfo:
    def test_create(self) -> None:
        info = CachedDataInfo(
            dataset="GLBX.MDP3",
            symbol="ES.c.0",
            schema="ohlcv-1m",
            ranges=[DateRange(start=date(2024, 1, 1), end=date(2024, 6, 30))],
            size_bytes=1024,
        )
        assert info.dataset == "GLBX.MDP3"
        assert info.schema_ == "ohlcv-1m"
        assert info.size_bytes == 1024


class TestCachedData:
    def test_empty_paths(self) -> None:
        data = CachedData([])
        assert data.paths == []
        assert data.to_polars().collect().is_empty()
        assert data.to_pandas().empty

    def test_with_parquet_files(self, tmp_path: Path) -> None:
        df = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        path = tmp_path / "test.parquet"
        df.write_parquet(path)

        data = CachedData([path])
        assert data.paths == [path]

        result = data.to_polars().collect()
        assert result.shape == (3, 2)

        pdf = data.to_pandas()
        assert len(pdf) == 3

    def test_multiple_files(self, tmp_path: Path) -> None:
        df1 = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        df2 = pl.DataFrame({"a": [3, 4], "b": ["z", "w"]})

        path1 = tmp_path / "01.parquet"
        path2 = tmp_path / "02.parquet"
        df1.write_parquet(path1)
        df2.write_parquet(path2)

        data = CachedData([path2, path1])
        assert data.paths == [path1, path2]

        result = data.to_polars().collect()
        assert result.shape == (4, 2)

    def test_repr(self) -> None:
        data = CachedData([Path("/a"), Path("/b")])
        assert "2 files" in repr(data)
