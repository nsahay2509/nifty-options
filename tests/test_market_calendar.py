from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from scripts.market_calendar import MarketCalendar


def test_weekend_and_custom_holiday_are_not_trading_days() -> None:
    calendar = MarketCalendar(holidays={date(2026, 4, 10): "Mock Holiday"})

    assert calendar.is_trading_day(date(2026, 4, 9)) is True
    assert calendar.is_trading_day(date(2026, 4, 10)) is False
    assert calendar.is_trading_day(date(2026, 4, 11)) is False
    assert calendar.holiday_name(date(2026, 4, 10)) == "Mock Holiday"


def test_session_window_uses_market_hours() -> None:
    calendar = MarketCalendar()

    window = calendar.session_window(date(2026, 4, 9))

    assert window.opens_at.hour == 9 and window.opens_at.minute == 15
    assert window.closes_at.hour == 15 and window.closes_at.minute == 30
    assert window.opens_at.tzinfo == ZoneInfo("Asia/Kolkata")


def test_expiry_tags_shift_back_when_expiry_is_holiday() -> None:
    calendar = MarketCalendar(holidays={date(2026, 4, 7): "Expiry Holiday"})

    expiry_day = calendar.describe_day(date(2026, 4, 6))
    expiry_eve = calendar.describe_day(date(2026, 4, 2))

    assert expiry_day.is_expiry_day is True
    assert expiry_day.next_expiry == date(2026, 4, 6)
    assert expiry_eve.is_expiry_eve is True
    assert "expiry_eve" in expiry_eve.tags


def test_classify_timestamp_reports_market_phase() -> None:
    calendar = MarketCalendar()
    tz = ZoneInfo("Asia/Kolkata")

    assert calendar.classify_timestamp(datetime(2026, 4, 9, 9, 0, tzinfo=tz)) == "pre_open"
    assert calendar.classify_timestamp(datetime(2026, 4, 9, 10, 0, tzinfo=tz)) == "open"
    assert calendar.classify_timestamp(datetime(2026, 4, 9, 16, 0, tzinfo=tz)) == "closed"
