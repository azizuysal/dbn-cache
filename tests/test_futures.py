from datetime import date

import pytest

from dbn_cache.futures import (
    ALL_SUPPORTED_ROOTS,
    EQUITY_INDEX_FUTURES,
    METAL_FUTURES,
    MONTH_CODES,
    TREASURY_FUTURES,
    generate_quarterly_contracts,
    get_contract_dates,
    get_expiration_date,
    is_supported_contract,
    is_supported_root,
    parse_contract_symbol,
    to_databento_symbol,
)


class TestParseContractSymbol:
    def test_basic_equity_index(self) -> None:
        root, month, year = parse_contract_symbol("NQH25")
        assert root == "NQ"
        assert month == 3
        assert year == 2025

    def test_december_contract(self) -> None:
        root, month, year = parse_contract_symbol("ESZ24")
        assert root == "ES"
        assert month == 12
        assert year == 2024

    def test_micro_contract(self) -> None:
        root, month, year = parse_contract_symbol("MESH25")
        assert root == "MES"
        assert month == 3
        assert year == 2025

    def test_m2k_contract(self) -> None:
        root, month, year = parse_contract_symbol("M2KH25")
        assert root == "M2K"
        assert month == 3
        assert year == 2025

    def test_treasury_contract(self) -> None:
        root, month, year = parse_contract_symbol("ZNH25")
        assert root == "ZN"
        assert month == 3
        assert year == 2025

    def test_metals_contract(self) -> None:
        root, month, year = parse_contract_symbol("GCJ25")
        assert root == "GC"
        assert month == 4
        assert year == 2025

    def test_case_insensitive(self) -> None:
        root1, month1, year1 = parse_contract_symbol("nqh25")
        root2, month2, year2 = parse_contract_symbol("NQH25")
        assert root1 == root2 == "NQ"
        assert month1 == month2 == 3
        assert year1 == year2 == 2025

    def test_mixed_case(self) -> None:
        root, month, year = parse_contract_symbol("Nqh25")
        assert root == "NQ"
        assert month == 3
        assert year == 2025

    def test_year_2020s(self) -> None:
        _, _, year = parse_contract_symbol("ESZ24")
        assert year == 2024
        _, _, year = parse_contract_symbol("ESZ29")
        assert year == 2029

    def test_year_2030s(self) -> None:
        _, _, year = parse_contract_symbol("ESZ30")
        assert year == 2030
        _, _, year = parse_contract_symbol("ESZ35")
        assert year == 2035

    def test_all_month_codes(self) -> None:
        for code, expected_month in MONTH_CODES.items():
            _, month, _ = parse_contract_symbol(f"ES{code}25")
            assert month == expected_month

    def test_invalid_not_futures_pattern(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            parse_contract_symbol("AAPL")

    def test_invalid_continuous_futures(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            parse_contract_symbol("ES.c.0")

    def test_invalid_parent_symbol(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            parse_contract_symbol("ES.FUT")

    def test_invalid_month_code(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            parse_contract_symbol("ESA25")  # A is not a valid month code

    def test_single_digit_year_rejected(self) -> None:
        """Single-digit years are rejected - use 2-digit years."""
        with pytest.raises(ValueError, match="Could not parse"):
            parse_contract_symbol("NQH5")

    def test_single_digit_year_all_rejected(self) -> None:
        """All single-digit years should be rejected."""
        for digit in range(10):
            with pytest.raises(ValueError, match="Could not parse"):
                parse_contract_symbol(f"ESZ{digit}")


class TestToDatabentoSymbol:
    def test_two_digit_to_single(self) -> None:
        assert to_databento_symbol("NQH25") == "NQH5"
        assert to_databento_symbol("ESZ24") == "ESZ4"
        assert to_databento_symbol("GCJ26") == "GCJ6"

    def test_micro_contract(self) -> None:
        assert to_databento_symbol("MESH25") == "MESH5"
        assert to_databento_symbol("M2KU24") == "M2KU4"

    def test_historical_contract(self) -> None:
        """For 2016, NQH16 becomes NQH6."""
        assert to_databento_symbol("NQH16") == "NQH6"
        assert to_databento_symbol("ESZ10") == "ESZ0"

    def test_case_insensitive(self) -> None:
        assert to_databento_symbol("nqh25") == "NQH5"
        assert to_databento_symbol("Esz24") == "ESZ4"

    def test_single_digit_rejected(self) -> None:
        """Single-digit years are rejected - use 2-digit years."""
        with pytest.raises(ValueError, match="Could not parse"):
            to_databento_symbol("NQH5")


class TestIsSupportedContract:
    def test_equity_index_supported(self) -> None:
        for root in EQUITY_INDEX_FUTURES:
            assert is_supported_contract(f"{root}H25") is True

    def test_treasury_supported(self) -> None:
        for root in TREASURY_FUTURES:
            assert is_supported_contract(f"{root}H25") is True

    def test_metals_supported(self) -> None:
        for root in METAL_FUTURES:
            assert is_supported_contract(f"{root}J25") is True

    def test_unsupported_vix(self) -> None:
        assert is_supported_contract("VXH25") is False

    def test_unsupported_corn(self) -> None:
        assert is_supported_contract("ZCH25") is False

    def test_stock_not_supported(self) -> None:
        assert is_supported_contract("AAPL") is False

    def test_continuous_not_supported(self) -> None:
        assert is_supported_contract("ES.c.0") is False

    def test_case_insensitive(self) -> None:
        assert is_supported_contract("nqh25") is True
        assert is_supported_contract("NQH25") is True


class TestIsSupportedRoot:
    def test_equity_index_roots(self) -> None:
        for root in EQUITY_INDEX_FUTURES:
            assert is_supported_root(root) is True

    def test_treasury_roots(self) -> None:
        for root in TREASURY_FUTURES:
            assert is_supported_root(root) is True

    def test_metals_roots(self) -> None:
        for root in METAL_FUTURES:
            assert is_supported_root(root) is True

    def test_unsupported_vix(self) -> None:
        assert is_supported_root("VX") is False

    def test_unsupported_corn(self) -> None:
        assert is_supported_root("ZC") is False

    def test_specific_contract_not_root(self) -> None:
        # Specific contracts should return False
        assert is_supported_root("NQH25") is False
        assert is_supported_root("ESZ24") is False

    def test_continuous_not_root(self) -> None:
        assert is_supported_root("ES.c.0") is False

    def test_case_insensitive(self) -> None:
        assert is_supported_root("nq") is True
        assert is_supported_root("NQ") is True
        assert is_supported_root("Nq") is True


class TestGenerateQuarterlyContracts:
    def test_single_year(self) -> None:
        contracts = generate_quarterly_contracts("NQ", 2024, 2024)
        assert contracts == ["NQH24", "NQM24", "NQU24", "NQZ24"]

    def test_multi_year(self) -> None:
        contracts = generate_quarterly_contracts("ES", 2024, 2025)
        expected = [
            "ESH24",
            "ESM24",
            "ESU24",
            "ESZ24",
            "ESH25",
            "ESM25",
            "ESU25",
            "ESZ25",
        ]
        assert contracts == expected

    def test_historical_range(self) -> None:
        contracts = generate_quarterly_contracts("NQ", 2016, 2017)
        assert contracts[0] == "NQH16"
        assert contracts[-1] == "NQZ17"
        assert len(contracts) == 8

    def test_case_insensitive(self) -> None:
        contracts1 = generate_quarterly_contracts("nq", 2024, 2024)
        contracts2 = generate_quarterly_contracts("NQ", 2024, 2024)
        assert contracts1 == contracts2

    def test_micro_contracts(self) -> None:
        contracts = generate_quarterly_contracts("MES", 2024, 2024)
        assert contracts == ["MESH24", "MESM24", "MESU24", "MESZ24"]

    def test_treasury_contracts(self) -> None:
        contracts = generate_quarterly_contracts("ZN", 2024, 2024)
        assert contracts == ["ZNH24", "ZNM24", "ZNU24", "ZNZ24"]

    def test_metals_contracts(self) -> None:
        contracts = generate_quarterly_contracts("GC", 2024, 2024)
        assert contracts == ["GCH24", "GCM24", "GCU24", "GCZ24"]

    def test_unsupported_root_raises(self) -> None:
        with pytest.raises(ValueError, match="not a supported futures root"):
            generate_quarterly_contracts("VX", 2024, 2024)

    def test_to_year_defaults_to_current(self) -> None:
        # Just verify it doesn't raise and returns contracts
        contracts = generate_quarterly_contracts("NQ", 2024)
        assert len(contracts) >= 4  # At least one year of contracts
        assert contracts[0] == "NQH24"


class TestGetExpirationDate:
    def test_equity_index_third_friday(self) -> None:
        # March 2025: 3rd Friday is March 21
        exp = get_expiration_date("NQ", 3, 2025)
        assert exp == date(2025, 3, 21)

    def test_equity_index_december(self) -> None:
        # December 2024: 3rd Friday is December 20
        exp = get_expiration_date("ES", 12, 2024)
        assert exp == date(2024, 12, 20)

    def test_micro_same_as_standard(self) -> None:
        es_exp = get_expiration_date("ES", 3, 2025)
        mes_exp = get_expiration_date("MES", 3, 2025)
        assert es_exp == mes_exp

    def test_all_equity_index_same_rules(self) -> None:
        # All equity index futures should have same expiration
        expirations = {
            get_expiration_date(root, 3, 2025) for root in EQUITY_INDEX_FUTURES
        }
        assert len(expirations) == 1  # All should be the same date

    def test_treasury_expiration(self) -> None:
        # March 2025: Last business day is March 31
        # 7 business days before = around March 20
        exp = get_expiration_date("ZN", 3, 2025)
        # Should be 7 business days before last business day of March
        assert exp.month == 3
        assert exp.year == 2025

    def test_metals_expiration(self) -> None:
        # April 2025: Last business day is April 30
        # 3rd last business day = around April 28
        exp = get_expiration_date("GC", 4, 2025)
        assert exp.month == 4
        assert exp.year == 2025

    def test_unsupported_product_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported product"):
            get_expiration_date("VX", 3, 2025)


class TestGetContractDates:
    def test_basic_nq_contract(self) -> None:
        start, end = get_contract_dates("NQH25")
        # NQH25 expires March 21, 2025
        assert end == date(2025, 3, 21)
        # Start is 14 days before NQZ24 expiration
        assert start.year == 2024
        assert start.month == 12

    def test_year_boundary(self) -> None:
        # NQH25 (March 2025) should look back to NQZ24 (December 2024)
        start, end = get_contract_dates("NQH25", rollover_days=14)
        assert start.year == 2024
        assert end.year == 2025

    def test_same_year(self) -> None:
        # NQU25 (September 2025) should look back to NQM25 (June 2025)
        start, end = get_contract_dates("NQU25", rollover_days=14)
        assert start.year == 2025
        assert end.year == 2025
        assert start.month == 6  # Approximately June (after M25 expiration - 14 days)

    def test_custom_rollover_days(self) -> None:
        start_14, end_14 = get_contract_dates("NQH25", rollover_days=14)
        start_7, end_7 = get_contract_dates("NQH25", rollover_days=7)

        # Same end date
        assert end_14 == end_7

        # start_7 should be later (shorter buffer)
        assert start_7 > start_14

    def test_zero_rollover_days(self) -> None:
        start, _ = get_contract_dates("NQH25", rollover_days=0)
        # Start should equal previous contract expiration exactly
        prev_exp = get_expiration_date("NQ", 12, 2024)  # NQZ24
        assert start == prev_exp

    def test_treasury_contract(self) -> None:
        _, end = get_contract_dates("ZNH25")
        assert end.year == 2025
        assert end.month == 3

    def test_metals_contract(self) -> None:
        _, end = get_contract_dates("GCJ25")
        assert end.year == 2025
        assert end.month == 4

    def test_unsupported_contract_raises(self) -> None:
        with pytest.raises(ValueError, match="not a supported product"):
            get_contract_dates("VXH25")

    def test_stock_symbol_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            get_contract_dates("AAPL")

    def test_case_insensitive(self) -> None:
        start1, end1 = get_contract_dates("nqh25")
        start2, end2 = get_contract_dates("NQH25")
        assert start1 == start2
        assert end1 == end2


class TestPreviousQuarterlyMonth:
    """Test the quarterly month lookback logic indirectly via get_contract_dates."""

    def test_march_to_december(self) -> None:
        # NQH25 (March) should look back to Z24 (December previous year)
        start, _ = get_contract_dates("NQH25", rollover_days=0)
        # Start should be December 2024 expiration
        assert start.month == 12
        assert start.year == 2024

    def test_june_to_march(self) -> None:
        # NQM25 (June) should look back to H25 (March same year)
        start, _ = get_contract_dates("NQM25", rollover_days=0)
        assert start.month == 3
        assert start.year == 2025

    def test_september_to_june(self) -> None:
        # NQU25 (September) should look back to M25 (June same year)
        start, _ = get_contract_dates("NQU25", rollover_days=0)
        assert start.month == 6
        assert start.year == 2025

    def test_december_to_september(self) -> None:
        # NQZ25 (December) should look back to U25 (September same year)
        start, _ = get_contract_dates("NQZ25", rollover_days=0)
        assert start.month == 9
        assert start.year == 2025


class TestEdgeCases:
    def test_all_supported_roots_have_consistent_coverage(self) -> None:
        """Verify all supported roots can calculate dates without error."""
        for root in ALL_SUPPORTED_ROOTS:
            # Should not raise
            _start, _end = get_contract_dates(f"{root}H25")
            assert _start < _end

    def test_leap_year_february(self) -> None:
        """Test metals/treasury expiration in February leap year."""
        # February 2024 is a leap year
        if "GC" in METAL_FUTURES:
            exp = get_expiration_date("GC", 2, 2024)
            assert exp.year == 2024
            assert exp.month == 2

    def test_non_leap_year_february(self) -> None:
        """Test metals/treasury expiration in February non-leap year."""
        # February 2025 is not a leap year
        if "GC" in METAL_FUTURES:
            exp = get_expiration_date("GC", 2, 2025)
            assert exp.year == 2025
            assert exp.month == 2

    def test_end_of_year_contract(self) -> None:
        """Test December contracts properly handle year boundaries."""
        start, _end = get_contract_dates("ESZ24")
        assert _end.year == 2024
        assert _end.month == 12
        # Previous contract is September
        assert start.month == 9
        assert start.year == 2024
