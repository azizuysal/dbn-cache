from datetime import date

import pytest

from dbn_cache.utils import (
    detect_stype,
    find_missing_date_ranges,
    get_partition_path,
    is_tick_schema,
    iter_days,
    iter_months,
    merge_date_ranges,
    month_start_end,
    normalize_symbol,
)


class TestNormalizeSymbol:
    def test_continuous_symbol(self) -> None:
        assert normalize_symbol("ES.c.0") == "ES_c_0"

    def test_parent_symbol(self) -> None:
        assert normalize_symbol("ES.FUT") == "ES_FUT"

    def test_explicit_contract(self) -> None:
        assert normalize_symbol("ESZ24") == "ESZ24"

    def test_multiple_dots(self) -> None:
        assert normalize_symbol("ES.v.1") == "ES_v_1"


class TestDetectStype:
    def test_continuous_calendar(self) -> None:
        assert detect_stype("ES.c.0") == "continuous"

    def test_continuous_volume(self) -> None:
        assert detect_stype("ES.v.0") == "continuous"

    def test_continuous_oi(self) -> None:
        assert detect_stype("ES.n.0") == "continuous"

    def test_continuous_back_month(self) -> None:
        assert detect_stype("ES.c.1") == "continuous"

    def test_parent(self) -> None:
        assert detect_stype("ES.FUT") == "parent"

    def test_explicit_contract(self) -> None:
        assert detect_stype("ESZ24") == "raw_symbol"

    def test_explicit_contract_with_numbers(self) -> None:
        assert detect_stype("6E.FUT") == "parent"
        assert detect_stype("6E.c.0") == "continuous"


class TestIsTickSchema:
    def test_tick_schemas(self) -> None:
        assert is_tick_schema("trades") is True
        assert is_tick_schema("mbp-1") is True
        assert is_tick_schema("mbp-10") is True
        assert is_tick_schema("mbo") is True

    def test_ohlcv_schemas(self) -> None:
        assert is_tick_schema("ohlcv-1s") is False
        assert is_tick_schema("ohlcv-1m") is False
        assert is_tick_schema("ohlcv-1h") is False
        assert is_tick_schema("ohlcv-1d") is False


class TestIterMonths:
    def test_single_month(self) -> None:
        result = list(iter_months(date(2024, 1, 15), date(2024, 1, 20)))
        assert result == [(2024, 1)]

    def test_multiple_months(self) -> None:
        result = list(iter_months(date(2024, 1, 1), date(2024, 3, 31)))
        assert result == [(2024, 1), (2024, 2), (2024, 3)]

    def test_year_boundary(self) -> None:
        result = list(iter_months(date(2023, 11, 1), date(2024, 2, 28)))
        assert result == [(2023, 11), (2023, 12), (2024, 1), (2024, 2)]


class TestIterDays:
    def test_single_day(self) -> None:
        result = list(iter_days(date(2024, 1, 1), date(2024, 1, 1)))
        assert result == [date(2024, 1, 1)]

    def test_multiple_days(self) -> None:
        result = list(iter_days(date(2024, 1, 1), date(2024, 1, 3)))
        assert result == [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]


class TestGetPartitionPath:
    def test_ohlcv_schema(self, tmp_path: pytest.TempPathFactory) -> None:
        from pathlib import Path

        base = Path("/cache/GLBX.MDP3/ES_c_0/ohlcv-1m")
        result = get_partition_path(base, "ohlcv-1m", 2024, 1)
        assert result == base / "2024" / "01.parquet"

    def test_tick_schema(self) -> None:
        from pathlib import Path

        base = Path("/cache/GLBX.MDP3/ES_c_0/trades")
        result = get_partition_path(base, "trades", 2024, 1, 15)
        assert result == base / "2024" / "01" / "15.parquet"

    def test_tick_schema_missing_day(self) -> None:
        from pathlib import Path

        base = Path("/cache")
        with pytest.raises(ValueError, match="Day required"):
            get_partition_path(base, "trades", 2024, 1)


class TestMonthStartEnd:
    def test_january(self) -> None:
        start, end = month_start_end(2024, 1)
        assert start == date(2024, 1, 1)
        assert end == date(2024, 1, 31)

    def test_february_leap_year(self) -> None:
        start, end = month_start_end(2024, 2)
        assert start == date(2024, 2, 1)
        assert end == date(2024, 2, 29)

    def test_february_non_leap_year(self) -> None:
        start, end = month_start_end(2023, 2)
        assert start == date(2023, 2, 1)
        assert end == date(2023, 2, 28)


class TestMergeDateRanges:
    def test_empty(self) -> None:
        assert merge_date_ranges([]) == []

    def test_single(self) -> None:
        ranges = [(date(2024, 1, 1), date(2024, 3, 31))]
        result = merge_date_ranges(ranges)
        assert len(result) == 1

    def test_overlapping(self) -> None:
        ranges = [
            (date(2024, 1, 1), date(2024, 3, 31)),
            (date(2024, 3, 1), date(2024, 6, 30)),
        ]
        result = merge_date_ranges(ranges)
        assert len(result) == 1
        assert result[0] == (date(2024, 1, 1), date(2024, 6, 30))

    def test_adjacent(self) -> None:
        ranges = [
            (date(2024, 1, 1), date(2024, 1, 31)),
            (date(2024, 2, 1), date(2024, 2, 29)),
        ]
        result = merge_date_ranges(ranges)
        assert len(result) == 1
        assert result[0] == (date(2024, 1, 1), date(2024, 2, 29))

    def test_gap(self) -> None:
        ranges = [
            (date(2024, 1, 1), date(2024, 1, 31)),
            (date(2024, 3, 1), date(2024, 3, 31)),
        ]
        result = merge_date_ranges(ranges)
        assert len(result) == 2


class TestFindMissingDateRanges:
    def test_no_cached(self) -> None:
        missing = find_missing_date_ranges(date(2024, 1, 1), date(2024, 3, 31), [])
        assert len(missing) == 1
        assert missing[0] == (date(2024, 1, 1), date(2024, 3, 31))

    def test_fully_cached(self) -> None:
        cached = [(date(2024, 1, 1), date(2024, 12, 31))]
        missing = find_missing_date_ranges(date(2024, 3, 1), date(2024, 6, 30), cached)
        assert len(missing) == 0

    def test_partial_start(self) -> None:
        cached = [(date(2024, 3, 1), date(2024, 12, 31))]
        missing = find_missing_date_ranges(date(2024, 1, 1), date(2024, 6, 30), cached)
        assert len(missing) == 1
        assert missing[0] == (date(2024, 1, 1), date(2024, 2, 29))

    def test_partial_end(self) -> None:
        cached = [(date(2024, 1, 1), date(2024, 3, 31))]
        missing = find_missing_date_ranges(date(2024, 1, 1), date(2024, 6, 30), cached)
        assert len(missing) == 1
        assert missing[0] == (date(2024, 4, 1), date(2024, 6, 30))
