"""Tests for exchange calendar integration.

These tests validate our understanding of the exchange_calendars library
and ensure correct handling of holidays and early close days.

Key findings:
- CME (CMES): Electronic trading hours, open most holidays but with early close
- NYSE (XNYS): Regular trading hours only, closed on federal holidays
- OPRA options follow NYSE schedule (no overnight trading)
- CME futures have nearly 24h electronic trading
"""

from datetime import date

import exchange_calendars as xcals
import pytest


class TestCMECalendar:
    """Tests for CME calendar (GLBX.MDP3 futures)."""

    @pytest.fixture
    def cme(self) -> xcals.ExchangeCalendar:
        """CME calendar for futures."""
        return xcals.get_calendar("CMES")

    def test_normal_trading_day(self, cme: xcals.ExchangeCalendar) -> None:
        """Regular trading day should be a session."""
        assert cme.is_session("2024-01-16") is True

    def test_weekend_closed(self, cme: xcals.ExchangeCalendar) -> None:
        """Weekends should not be sessions."""
        assert cme.is_session("2024-01-13") is False  # Saturday
        assert cme.is_session("2024-01-14") is False  # Sunday

    def test_mlk_day_open_early_close(self, cme: xcals.ExchangeCalendar) -> None:
        """MLK Day: CME is OPEN but with early close."""
        mlk_day = "2024-01-15"
        assert cme.is_session(mlk_day) is True
        # Early close at 12:00 CT = 18:00 UTC
        close = cme.session_close(mlk_day)
        assert close.hour == 18  # 18:00 UTC

    def test_presidents_day_open_early_close(self, cme: xcals.ExchangeCalendar) -> None:
        """Presidents Day: CME is OPEN but with early close."""
        assert cme.is_session("2024-02-19") is True

    def test_july_4th_open_early_close(self, cme: xcals.ExchangeCalendar) -> None:
        """July 4th: CME is OPEN but with early close."""
        july_4th = "2024-07-04"
        assert cme.is_session(july_4th) is True
        # Early close at 12:00 CT = 17:00 UTC (DST)
        close = cme.session_close(july_4th)
        assert close.hour == 17

    def test_christmas_closed(self, cme: xcals.ExchangeCalendar) -> None:
        """Christmas: CME is CLOSED."""
        assert cme.is_session("2024-12-25") is False

    def test_new_years_closed(self, cme: xcals.ExchangeCalendar) -> None:
        """New Year's Day: CME is CLOSED."""
        assert cme.is_session("2024-01-01") is False

    def test_electronic_trading_hours(self, cme: xcals.ExchangeCalendar) -> None:
        """CME has nearly 24h electronic trading hours."""
        # Normal day: opens 17:00 CT previous day, closes 17:00 CT
        open_time = cme.session_open("2024-01-16")
        close_time = cme.session_close("2024-01-16")
        # Open is previous day 23:00 UTC (17:00 CT)
        assert open_time.day == 15  # Previous day
        assert open_time.hour == 23
        # Close is 23:00 UTC (17:00 CT)
        assert close_time.hour == 23

    def test_early_close_in_early_closes_property(
        self, cme: xcals.ExchangeCalendar
    ) -> None:
        """Early close days should be in early_closes property."""
        early_close_dates = [d.date() for d in cme.early_closes]
        # MLK Day 2024 is an early close
        assert date(2024, 1, 15) in early_close_dates
        # July 4th 2024 is an early close
        assert date(2024, 7, 4) in early_close_dates


class TestNYSECalendar:
    """Tests for NYSE calendar (OPRA.PILLAR options)."""

    @pytest.fixture
    def nyse(self) -> xcals.ExchangeCalendar:
        """NYSE calendar for equities/options."""
        return xcals.get_calendar("XNYS")

    def test_normal_trading_day(self, nyse: xcals.ExchangeCalendar) -> None:
        """Regular trading day should be a session."""
        assert nyse.is_session("2024-01-16") is True

    def test_weekend_closed(self, nyse: xcals.ExchangeCalendar) -> None:
        """Weekends should not be sessions."""
        assert nyse.is_session("2024-01-13") is False
        assert nyse.is_session("2024-01-14") is False

    def test_mlk_day_closed(self, nyse: xcals.ExchangeCalendar) -> None:
        """MLK Day: NYSE is CLOSED (unlike CME)."""
        assert nyse.is_session("2024-01-15") is False

    def test_presidents_day_closed(self, nyse: xcals.ExchangeCalendar) -> None:
        """Presidents Day: NYSE is CLOSED."""
        assert nyse.is_session("2024-02-19") is False

    def test_memorial_day_closed(self, nyse: xcals.ExchangeCalendar) -> None:
        """Memorial Day: NYSE is CLOSED."""
        assert nyse.is_session("2024-05-27") is False

    def test_july_4th_closed(self, nyse: xcals.ExchangeCalendar) -> None:
        """July 4th: NYSE is CLOSED."""
        assert nyse.is_session("2024-07-04") is False

    def test_labor_day_closed(self, nyse: xcals.ExchangeCalendar) -> None:
        """Labor Day: NYSE is CLOSED."""
        assert nyse.is_session("2024-09-02") is False

    def test_thanksgiving_closed(self, nyse: xcals.ExchangeCalendar) -> None:
        """Thanksgiving: NYSE is CLOSED."""
        assert nyse.is_session("2024-11-28") is False

    def test_christmas_closed(self, nyse: xcals.ExchangeCalendar) -> None:
        """Christmas: NYSE is CLOSED."""
        assert nyse.is_session("2024-12-25") is False

    def test_regular_trading_hours(self, nyse: xcals.ExchangeCalendar) -> None:
        """NYSE has regular trading hours only (no overnight)."""
        open_time = nyse.session_open("2024-01-16")
        close_time = nyse.session_close("2024-01-16")
        # Open is 14:30 UTC (09:30 ET)
        assert open_time.hour == 14
        assert open_time.minute == 30
        # Close is 21:00 UTC (16:00 ET)
        assert close_time.hour == 21


class TestNYSEEarlyCloses:
    """Tests for NYSE early close days."""

    @pytest.fixture
    def nyse(self) -> xcals.ExchangeCalendar:
        """NYSE calendar."""
        return xcals.get_calendar("XNYS")

    def test_july_3rd_early_close(self, nyse: xcals.ExchangeCalendar) -> None:
        """July 3rd 2024: Early close at 13:00 ET."""
        july_3rd = "2024-07-03"
        assert nyse.is_session(july_3rd) is True
        close = nyse.session_close(july_3rd)
        # 13:00 ET = 17:00 UTC
        assert close.hour == 17

    def test_black_friday_early_close(self, nyse: xcals.ExchangeCalendar) -> None:
        """Black Friday 2024: Early close at 13:00 ET."""
        black_friday = "2024-11-29"
        assert nyse.is_session(black_friday) is True
        close = nyse.session_close(black_friday)
        # 13:00 ET = 18:00 UTC (standard time)
        assert close.hour == 18

    def test_christmas_eve_early_close(self, nyse: xcals.ExchangeCalendar) -> None:
        """Christmas Eve 2024: Early close at 13:00 ET."""
        xmas_eve = "2024-12-24"
        assert nyse.is_session(xmas_eve) is True
        close = nyse.session_close(xmas_eve)
        # 13:00 ET = 18:00 UTC
        assert close.hour == 18

    def test_early_close_times_vs_normal(self, nyse: xcals.ExchangeCalendar) -> None:
        """Early close should be before normal close (comparing time of day)."""
        normal_close = nyse.session_close("2024-01-16")  # Normal day
        early_close = nyse.session_close("2024-11-29")  # Black Friday
        # Compare time of day, not full timestamps
        assert early_close.time() < normal_close.time()

    def test_early_closes_property(self, nyse: xcals.ExchangeCalendar) -> None:
        """Early close days should be in early_closes property."""
        early_close_dates = [d.date() for d in nyse.early_closes]
        assert date(2024, 7, 3) in early_close_dates  # Day before July 4th
        assert date(2024, 11, 29) in early_close_dates  # Black Friday
        assert date(2024, 12, 24) in early_close_dates  # Christmas Eve


class TestSessionsInRange:
    """Tests for getting trading sessions in a range."""

    @pytest.fixture
    def nyse(self) -> xcals.ExchangeCalendar:
        """NYSE calendar."""
        return xcals.get_calendar("XNYS")

    @pytest.fixture
    def cme(self) -> xcals.ExchangeCalendar:
        """CME calendar."""
        return xcals.get_calendar("CMES")

    def test_nyse_sessions_skip_mlk_day(self, nyse: xcals.ExchangeCalendar) -> None:
        """NYSE sessions_in_range should skip MLK Day."""
        sessions = nyse.sessions_in_range("2024-01-12", "2024-01-17")
        session_dates = [s.date() for s in sessions]
        # MLK Day should NOT be in sessions
        assert date(2024, 1, 15) not in session_dates
        # Adjacent trading days should be
        assert date(2024, 1, 12) in session_dates
        assert date(2024, 1, 16) in session_dates

    def test_cme_sessions_include_mlk_day(self, cme: xcals.ExchangeCalendar) -> None:
        """CME sessions_in_range SHOULD include MLK Day (early close)."""
        sessions = cme.sessions_in_range("2024-01-12", "2024-01-17")
        session_dates = [s.date() for s in sessions]
        # MLK Day SHOULD be in sessions for CME
        assert date(2024, 1, 15) in session_dates

    def test_sessions_skip_weekends(self, nyse: xcals.ExchangeCalendar) -> None:
        """sessions_in_range should skip weekends."""
        sessions = nyse.sessions_in_range("2024-01-12", "2024-01-17")
        session_dates = [s.date() for s in sessions]
        assert date(2024, 1, 13) not in session_dates  # Saturday
        assert date(2024, 1, 14) not in session_dates  # Sunday


class TestIsEarlyClose:
    """Tests for detecting early close days."""

    @pytest.fixture
    def nyse(self) -> xcals.ExchangeCalendar:
        """NYSE calendar."""
        return xcals.get_calendar("XNYS")

    def test_is_early_close_helper(self, nyse: xcals.ExchangeCalendar) -> None:
        """Test helper function to detect early close."""
        early_close_dates = set(d.date() for d in nyse.early_closes)

        def is_early_close(d: date) -> bool:
            return d in early_close_dates

        assert is_early_close(date(2024, 11, 29)) is True  # Black Friday
        assert is_early_close(date(2024, 1, 16)) is False  # Normal day


class TestCalendarCaching:
    """Tests for calendar instance caching."""

    def test_same_calendar_instance_returned(self) -> None:
        """get_calendar returns same instance for same calendar name."""
        cal1 = xcals.get_calendar("CMES")
        cal2 = xcals.get_calendar("CMES")
        # exchange_calendars caches internally
        assert cal1 is cal2

    def test_different_calendars_different_instances(self) -> None:
        """Different calendars return different instances."""
        cme = xcals.get_calendar("CMES")
        nyse = xcals.get_calendar("XNYS")
        assert cme is not nyse


class TestDatasetCalendarMapping:
    """Tests to document which calendar to use for each dataset."""

    def test_glbx_uses_cme_calendar(self) -> None:
        """GLBX.MDP3 (CME futures) should use CMES calendar."""
        # Document the mapping
        dataset_to_calendar = {
            "GLBX.MDP3": "CMES",
            "OPRA.PILLAR": "XNYS",
            "XNAS.ITCH": "XNYS",
            "DBEQ.BASIC": "XNYS",
        }
        assert dataset_to_calendar["GLBX.MDP3"] == "CMES"

    def test_opra_uses_nyse_calendar(self) -> None:
        """OPRA.PILLAR (options) should use XNYS calendar."""
        # Options follow NYSE schedule
        nyse = xcals.get_calendar("XNYS")
        # MLK Day - no options trading
        assert nyse.is_session("2024-01-15") is False


class TestCalendarModule:
    """Tests for the dbn_cache.calendar module."""

    def test_is_trading_day_cme_mlk_day(self) -> None:
        """CME should be open on MLK Day."""
        from dbn_cache.calendar import is_trading_day

        # CME is open on MLK Day (early close)
        assert is_trading_day(date(2024, 1, 15), "GLBX.MDP3") is True

    def test_is_trading_day_opra_mlk_day(self) -> None:
        """OPRA should be closed on MLK Day."""
        from dbn_cache.calendar import is_trading_day

        # OPRA follows NYSE - closed on MLK Day
        assert is_trading_day(date(2024, 1, 15), "OPRA.PILLAR") is False

    def test_is_trading_day_weekend(self) -> None:
        """Both should be closed on weekends."""
        from dbn_cache.calendar import is_trading_day

        saturday = date(2024, 1, 13)
        assert is_trading_day(saturday, "GLBX.MDP3") is False
        assert is_trading_day(saturday, "OPRA.PILLAR") is False

    def test_is_early_close_cme_mlk_day(self) -> None:
        """CME MLK Day should be an early close."""
        from dbn_cache.calendar import is_early_close

        assert is_early_close(date(2024, 1, 15), "GLBX.MDP3") is True

    def test_is_early_close_nyse_black_friday(self) -> None:
        """NYSE Black Friday should be an early close."""
        from dbn_cache.calendar import is_early_close

        assert is_early_close(date(2024, 11, 29), "OPRA.PILLAR") is True

    def test_is_early_close_normal_day(self) -> None:
        """Normal trading day should not be early close."""
        from dbn_cache.calendar import is_early_close

        assert is_early_close(date(2024, 1, 16), "GLBX.MDP3") is False
        assert is_early_close(date(2024, 1, 16), "OPRA.PILLAR") is False

    def test_iter_trading_days_skips_holidays(self) -> None:
        """iter_trading_days should skip holidays for OPRA."""
        from dbn_cache.calendar import iter_trading_days

        # Range includes MLK Day (2024-01-15)
        days = list(
            iter_trading_days(date(2024, 1, 12), date(2024, 1, 17), "OPRA.PILLAR")
        )
        # MLK Day should not be in the list
        assert date(2024, 1, 15) not in days
        # But adjacent trading days should be
        assert date(2024, 1, 12) in days
        assert date(2024, 1, 16) in days

    def test_iter_trading_days_includes_early_close(self) -> None:
        """iter_trading_days should include early close days for CME."""
        from dbn_cache.calendar import iter_trading_days

        # Range includes MLK Day (2024-01-15) which is early close for CME
        days = list(
            iter_trading_days(date(2024, 1, 12), date(2024, 1, 17), "GLBX.MDP3")
        )
        # MLK Day SHOULD be in the list for CME
        assert date(2024, 1, 15) in days

    def test_iter_trading_days_skips_weekends(self) -> None:
        """iter_trading_days should skip weekends."""
        from dbn_cache.calendar import iter_trading_days

        days = list(
            iter_trading_days(date(2024, 1, 12), date(2024, 1, 17), "OPRA.PILLAR")
        )
        assert date(2024, 1, 13) not in days  # Saturday
        assert date(2024, 1, 14) not in days  # Sunday

    def test_get_session_close_normal_day(self) -> None:
        """Get session close time for normal day."""
        from dbn_cache.calendar import get_session_close

        close = get_session_close(date(2024, 1, 16), "OPRA.PILLAR")
        assert close is not None
        # NYSE closes at 21:00 UTC (16:00 ET)
        assert close == (21, 0)

    def test_get_session_close_early_close(self) -> None:
        """Get session close time for early close day."""
        from dbn_cache.calendar import get_session_close

        close = get_session_close(date(2024, 11, 29), "OPRA.PILLAR")  # Black Friday
        assert close is not None
        # Early close at 18:00 UTC (13:00 ET)
        assert close == (18, 0)

    def test_get_session_close_holiday(self) -> None:
        """Get session close for holiday returns None."""
        from dbn_cache.calendar import get_session_close

        close = get_session_close(date(2024, 1, 15), "OPRA.PILLAR")  # MLK Day
        assert close is None

    def test_get_trading_day_count(self) -> None:
        """Count trading days in range."""
        from dbn_cache.calendar import get_trading_day_count

        # Week with MLK Day holiday for OPRA
        count = get_trading_day_count(
            date(2024, 1, 12), date(2024, 1, 17), "OPRA.PILLAR"
        )
        # Fri 12, Mon 15 (holiday), Tue 16, Wed 17 = 3 trading days
        assert count == 3

    def test_get_next_trading_day_from_holiday(self) -> None:
        """Get next trading day from a holiday."""
        from dbn_cache.calendar import get_next_trading_day

        next_day = get_next_trading_day(date(2024, 1, 15), "OPRA.PILLAR")
        assert next_day == date(2024, 1, 16)

    def test_get_next_trading_day_from_trading_day(self) -> None:
        """Get next trading day from a trading day returns same day."""
        from dbn_cache.calendar import get_next_trading_day

        next_day = get_next_trading_day(date(2024, 1, 16), "OPRA.PILLAR")
        assert next_day == date(2024, 1, 16)

    def test_get_previous_trading_day_from_holiday(self) -> None:
        """Get previous trading day from a holiday."""
        from dbn_cache.calendar import get_previous_trading_day

        prev_day = get_previous_trading_day(date(2024, 1, 15), "OPRA.PILLAR")
        assert prev_day == date(2024, 1, 12)

    def test_unknown_dataset_uses_default_calendar(self) -> None:
        """Unknown dataset should use default (NYSE) calendar."""
        from dbn_cache.calendar import is_trading_day

        # Unknown dataset uses XNYS by default
        assert is_trading_day(date(2024, 1, 15), "UNKNOWN.DATASET") is False
