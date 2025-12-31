from datetime import date, datetime
from pathlib import Path

import polars as pl

from dbn_cache.models import (
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

    def test_date_filtering_single_day(self, tmp_path: Path) -> None:
        # Create test data with ts_event in nanoseconds since epoch
        # Dec 14, 15, 16 2021 at midnight UTC
        dec_14_ns = int(datetime(2021, 12, 14).timestamp() * 1e9)
        dec_15_ns = int(datetime(2021, 12, 15).timestamp() * 1e9)
        dec_16_ns = int(datetime(2021, 12, 16).timestamp() * 1e9)

        df = pl.DataFrame(
            {
                "ts_event": [dec_14_ns, dec_15_ns, dec_16_ns],
                "price": [100.0, 101.0, 102.0],
            }
        )
        path = tmp_path / "test.parquet"
        df.write_parquet(path)

        # Request only Dec 15
        data = CachedData([path], start=date(2021, 12, 15), end=date(2021, 12, 15))
        result = data.to_polars().collect()
        assert result.shape[0] == 1
        assert result["price"][0] == 101.0

    def test_date_filtering_range(self, tmp_path: Path) -> None:
        # Create test data spanning a month
        timestamps: list[int] = []
        prices: list[float] = []
        for day in range(1, 31):
            ts = int(datetime(2021, 12, day, 12, 0, 0).timestamp() * 1e9)
            timestamps.append(ts)
            prices.append(float(day))

        df = pl.DataFrame({"ts_event": timestamps, "price": prices})
        path = tmp_path / "test.parquet"
        df.write_parquet(path)

        # Request Dec 10-20
        data = CachedData([path], start=date(2021, 12, 10), end=date(2021, 12, 20))
        result = data.to_polars().collect()
        assert result.shape[0] == 11  # Days 10-20 inclusive
        assert result["price"].min() == 10.0
        assert result["price"].max() == 20.0

    def test_date_filtering_no_filter(self, tmp_path: Path) -> None:
        ts = int(datetime(2021, 12, 15).timestamp() * 1e9)
        df = pl.DataFrame({"ts_event": [ts], "price": [100.0]})
        path = tmp_path / "test.parquet"
        df.write_parquet(path)

        # No date filter - should return all data
        data = CachedData([path])
        result = data.to_polars().collect()
        assert result.shape[0] == 1

    def test_date_filtering_no_ts_event_column(self, tmp_path: Path) -> None:
        # Data without ts_event column should not be filtered
        df = pl.DataFrame({"other_col": [1, 2, 3], "price": [100.0, 101.0, 102.0]})
        path = tmp_path / "test.parquet"
        df.write_parquet(path)

        data = CachedData([path], start=date(2021, 12, 15), end=date(2021, 12, 15))
        result = data.to_polars().collect()
        assert result.shape[0] == 3  # All rows returned

    def test_date_filtering_pandas(self, tmp_path: Path) -> None:
        dec_14_ns = int(datetime(2021, 12, 14).timestamp() * 1e9)
        dec_15_ns = int(datetime(2021, 12, 15).timestamp() * 1e9)
        dec_16_ns = int(datetime(2021, 12, 16).timestamp() * 1e9)

        df = pl.DataFrame(
            {
                "ts_event": [dec_14_ns, dec_15_ns, dec_16_ns],
                "price": [100.0, 101.0, 102.0],
            }
        )
        path = tmp_path / "test.parquet"
        df.write_parquet(path)

        data = CachedData([path], start=date(2021, 12, 15), end=date(2021, 12, 15))
        pdf = data.to_pandas()
        assert len(pdf) == 1
        assert pdf["price"].iloc[0] == 101.0
