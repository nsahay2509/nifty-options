"""Trading-day calendar, session windows, and expiry tagging for the NIFTY runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from scripts.config import APP_CONFIG


DEFAULT_NSE_HOLIDAYS: dict[date, str] = {
    date(2026, 1, 15): "Municipal Corporation Election - Maharashtra",
    date(2026, 1, 26): "Republic Day",
    date(2026, 3, 3): "Holi",
    date(2026, 3, 26): "Shri Ram Navami",
    date(2026, 3, 31): "Shri Mahavir Jayanti",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    date(2026, 5, 1): "Maharashtra Day",
    date(2026, 5, 28): "Bakri Id",
    date(2026, 6, 26): "Muharram",
    date(2026, 9, 14): "Ganesh Chaturthi",
    date(2026, 10, 2): "Mahatma Gandhi Jayanti",
    date(2026, 10, 20): "Dussehra",
    date(2026, 11, 10): "Diwali-Balipratipada",
    date(2026, 11, 24): "Prakash Gurpurb Sri Guru Nanak Dev",
    date(2026, 12, 25): "Christmas",
}


@dataclass(frozen=True)
class SessionWindow:
    """Represents one regular NSE trading session window."""

    session_date: date
    opens_at: datetime
    closes_at: datetime


@dataclass(frozen=True)
class TradingDayContext:
    """Structured context for one market day."""

    session_date: date
    is_trading_day: bool
    holiday_name: str | None
    session_window: SessionWindow
    next_expiry: date | None
    days_to_expiry: int | None
    is_expiry_day: bool
    is_expiry_eve: bool
    tags: tuple[str, ...]


class MarketCalendar:
    """Owns holiday checks, session timings, and expiry-day classification."""

    def __init__(
        self,
        *,
        holidays: dict[date, str] | None = None,
        timezone_name: str | None = None,
        session_open: time | None = None,
        session_close: time | None = None,
        weekly_expiry_weekday: int | None = None,
    ) -> None:
        session_config = APP_CONFIG.session
        self.timezone = ZoneInfo(timezone_name or session_config.market_timezone)
        self.session_open = session_open or time(
            hour=session_config.regular_open_hour,
            minute=session_config.regular_open_minute,
            tzinfo=self.timezone,
        )
        self.session_close = session_close or time(
            hour=session_config.regular_close_hour,
            minute=session_config.regular_close_minute,
            tzinfo=self.timezone,
        )
        self.weekly_expiry_weekday = (
            session_config.weekly_expiry_weekday
            if weekly_expiry_weekday is None
            else weekly_expiry_weekday
        )
        self.holidays = dict(DEFAULT_NSE_HOLIDAYS)
        if holidays:
            self.holidays.update(holidays)

    def today(self) -> date:
        """Return the current market date in IST."""
        return datetime.now(self.timezone).date()

    def as_market_datetime(self, value: datetime | date | None = None) -> datetime:
        """Normalize any datetime into the market timezone."""
        if value is None:
            return datetime.now(self.timezone)
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=self.timezone)
            return value.astimezone(self.timezone)
        return datetime.combine(value, time.min, self.timezone)

    def as_market_date(self, value: datetime | date | None = None) -> date:
        """Normalize any supported date-like value into the market session date."""
        if isinstance(value, datetime):
            return self.as_market_datetime(value).date()
        if isinstance(value, date):
            return value
        return self.today()

    def is_weekend(self, value: datetime | date) -> bool:
        """Return true when the day falls on Saturday or Sunday."""
        return self.as_market_date(value).weekday() >= 5

    def holiday_name(self, value: datetime | date) -> str | None:
        """Return the configured holiday label for the given date, if any."""
        return self.holidays.get(self.as_market_date(value))

    def is_holiday(self, value: datetime | date) -> bool:
        """Return true when the day is an exchange holiday."""
        return self.holiday_name(value) is not None

    def is_trading_day(self, value: datetime | date) -> bool:
        """Return true when the exchange is open for the regular session."""
        session_date = self.as_market_date(value)
        return not self.is_weekend(session_date) and not self.is_holiday(session_date)

    def session_window(self, value: datetime | date) -> SessionWindow:
        """Return the regular-session open and close timestamps for a day."""
        session_date = self.as_market_date(value)
        return SessionWindow(
            session_date=session_date,
            opens_at=datetime.combine(session_date, self.session_open),
            closes_at=datetime.combine(session_date, self.session_close),
        )

    def classify_timestamp(self, value: datetime | None = None) -> str:
        """Classify the current runtime phase for a specific timestamp."""
        now = self.as_market_datetime(value)
        if not self.is_trading_day(now):
            return "holiday" if self.is_holiday(now) else "weekend"

        window = self.session_window(now)
        if now < window.opens_at:
            return "pre_open"
        if now <= window.closes_at:
            return "open"
        return "closed"

    def next_trading_day(self, value: datetime | date) -> date:
        """Return the next valid trading day after the given date."""
        cursor = self.as_market_date(value) + timedelta(days=1)
        while not self.is_trading_day(cursor):
            cursor += timedelta(days=1)
        return cursor

    def previous_trading_day(self, value: datetime | date) -> date:
        """Return the previous valid trading day before the given date."""
        cursor = self.as_market_date(value) - timedelta(days=1)
        while not self.is_trading_day(cursor):
            cursor -= timedelta(days=1)
        return cursor

    def next_expiry(self, value: datetime | date) -> date:
        """Return the next weekly NIFTY expiry, shifting back for holidays."""
        session_date = self.as_market_date(value)
        days_ahead = (self.weekly_expiry_weekday - session_date.weekday()) % 7
        candidate = session_date + timedelta(days=days_ahead)

        while not self.is_trading_day(candidate):
            candidate -= timedelta(days=1)
        return candidate

    def monthly_expiry(self, year: int, month: int) -> date:
        """Return the monthly expiry date for a given month, adjusted for holidays."""
        if month == 12:
            cursor = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            cursor = date(year, month + 1, 1) - timedelta(days=1)

        while cursor.weekday() != self.weekly_expiry_weekday:
            cursor -= timedelta(days=1)
        while not self.is_trading_day(cursor):
            cursor -= timedelta(days=1)
        return cursor

    def describe_day(self, value: datetime | date) -> TradingDayContext:
        """Return the day context used by the runtime and session-feature layers."""
        session_date = self.as_market_date(value)
        is_trading_day = self.is_trading_day(session_date)
        next_open_day = session_date if is_trading_day else self.next_trading_day(session_date)
        next_expiry = self.next_expiry(next_open_day)
        days_to_expiry = (next_expiry - session_date).days
        is_expiry_day = is_trading_day and session_date == next_expiry
        is_expiry_eve = is_trading_day and not is_expiry_day and session_date == self.previous_trading_day(next_expiry)
        is_monthly_expiry = next_expiry == self.monthly_expiry(next_expiry.year, next_expiry.month)

        tags: list[str] = []
        if is_trading_day:
            tags.append("trading_day")
        else:
            tags.append("market_closed_day")
            if self.is_weekend(session_date):
                tags.append("weekend")
            if self.is_holiday(session_date):
                tags.append("holiday")
        if is_expiry_day:
            tags.append("expiry_day")
        if is_expiry_eve:
            tags.append("expiry_eve")
        tags.append("monthly_expiry" if is_monthly_expiry else "weekly_expiry")

        return TradingDayContext(
            session_date=session_date,
            is_trading_day=is_trading_day,
            holiday_name=self.holiday_name(session_date),
            session_window=self.session_window(next_open_day),
            next_expiry=next_expiry,
            days_to_expiry=days_to_expiry,
            is_expiry_day=is_expiry_day,
            is_expiry_eve=is_expiry_eve,
            tags=tuple(tags),
        )
