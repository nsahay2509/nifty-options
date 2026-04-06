"""Reusable session feature derivation for the rebuilt NIFTY runtime."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from scripts.config import APP_CONFIG
from scripts.log import get_logger
from scripts.market_calendar import MarketCalendar
from scripts.schema import Candle, PriorDayLevels, SessionReferences, SessionSnapshot


logger = get_logger("session_features")


def _require_candles(candles: Sequence[Candle], *, label: str) -> list[Candle]:
    ordered = sorted(candles, key=lambda candle: candle.start)
    if not ordered:
        raise ValueError(f"At least one candle is required to derive {label}")
    return ordered


def derive_prior_day_levels(candles: Sequence[Candle]) -> PriorDayLevels:
    """Derive previous-session OHLC reference levels from completed candles."""
    ordered = _require_candles(candles, label="prior-day levels")
    high = max(candle.high for candle in ordered)
    low = min(candle.low for candle in ordered)
    levels = PriorDayLevels(
        session_date=ordered[0].start.date().isoformat(),
        open=ordered[0].open,
        high=high,
        low=low,
        close=ordered[-1].close,
        midpoint=(high + low) / 2,
        range_points=high - low,
    )
    logger.info(
        "PRIOR_DAY_LEVELS | session_date=%s high=%s low=%s close=%s range=%s",
        levels.session_date,
        levels.high,
        levels.low,
        levels.close,
        levels.range_points,
    )
    return levels


def derive_session_references(
    candles: Sequence[Candle],
    *,
    opening_range_minutes: int | None = None,
) -> SessionReferences:
    """Derive opening-range and intraday session references from active-session candles."""
    ordered = _require_candles(candles, label="session references")
    opening_minutes = opening_range_minutes or APP_CONFIG.session.opening_range_minutes
    session_start = ordered[0].start
    opening_cutoff = session_start + timedelta(minutes=opening_minutes)
    opening_range_candles = [candle for candle in ordered if candle.start < opening_cutoff]
    if not opening_range_candles:
        opening_range_candles = [ordered[0]]

    intraday_high = max(candle.high for candle in ordered)
    intraday_low = min(candle.low for candle in ordered)
    refs = SessionReferences(
        session_date=session_start.date().isoformat(),
        opening_range_high=max(candle.high for candle in opening_range_candles),
        opening_range_low=min(candle.low for candle in opening_range_candles),
        intraday_high=intraday_high,
        intraday_low=intraday_low,
        session_midpoint=(intraday_high + intraday_low) / 2,
        realized_range=intraday_high - intraday_low,
        derived_from_interval_min=ordered[0].interval_min,
    )
    logger.info(
        "SESSION_REFERENCES | session_date=%s or_high=%s or_low=%s intraday_high=%s intraday_low=%s range=%s",
        refs.session_date,
        refs.opening_range_high,
        refs.opening_range_low,
        refs.intraday_high,
        refs.intraday_low,
        refs.realized_range,
    )
    return refs


class SessionFeatureEngine:
    """Builds state-engine-ready session features from candle inputs."""

    def __init__(
        self,
        *,
        calendar: MarketCalendar | None = None,
        opening_range_minutes: int | None = None,
    ) -> None:
        self.calendar = calendar or MarketCalendar()
        self.opening_range_minutes = opening_range_minutes or APP_CONFIG.session.opening_range_minutes
        self.logger = logger

    def classify_session_phase(self, timestamp: datetime) -> str:
        """Classify the intraday phase used by downstream state logic."""
        market_timestamp = self.calendar.as_market_datetime(timestamp)
        day_context = self.calendar.describe_day(market_timestamp)
        if not day_context.is_trading_day:
            return "holiday" if day_context.holiday_name else "weekend"

        session_window = day_context.session_window
        if market_timestamp < session_window.opens_at:
            return "pre_open"

        opening_range_end = session_window.opens_at + timedelta(minutes=self.opening_range_minutes)
        early_session_end = session_window.opens_at + timedelta(hours=1)
        late_session_start = session_window.closes_at - timedelta(hours=1)

        if market_timestamp < opening_range_end:
            return "opening_range"
        if market_timestamp < early_session_end:
            return "early_session"
        if market_timestamp < late_session_start:
            return "mid_session"
        if market_timestamp <= session_window.closes_at:
            return "late_session"
        return "post_close"

    def build_session_snapshot(
        self,
        *,
        timestamp: datetime,
        index_candle: Candle | None = None,
        futures_candle: Candle | None = None,
        session_candles: Sequence[Candle] = (),
        prior_day_candles: Sequence[Candle] = (),
    ) -> SessionSnapshot:
        """Build a `SessionSnapshot` from candles plus calendar-derived context."""
        market_timestamp = self.calendar.as_market_datetime(timestamp)
        day_context = self.calendar.describe_day(market_timestamp)
        prior_day_levels = derive_prior_day_levels(prior_day_candles) if prior_day_candles else None
        session_references = (
            derive_session_references(session_candles, opening_range_minutes=self.opening_range_minutes)
            if session_candles
            else None
        )
        session_phase = self.classify_session_phase(market_timestamp)

        session_open = session_candles[0].open if session_candles else (index_candle.open if index_candle else 0.0)
        snapshot = SessionSnapshot(
            timestamp=market_timestamp,
            index_candle=index_candle,
            futures_candle=futures_candle,
            prior_day_levels=prior_day_levels,
            session_references=session_references,
            days_to_expiry=day_context.days_to_expiry,
            session_phase=session_phase,
            raw_context={
                "holiday_name": day_context.holiday_name,
                "next_expiry": day_context.next_expiry.isoformat() if day_context.next_expiry else "",
                "is_expiry_day": day_context.is_expiry_day,
                "is_expiry_eve": day_context.is_expiry_eve,
                "trading_day_tags": day_context.tags,
                "session_open": session_open,
                "current_price": index_candle.close if index_candle else 0.0,
                "opening_range_width": (
                    session_references.opening_range_high - session_references.opening_range_low
                    if session_references is not None
                    else 0.0
                ),
            },
        )
        self.logger.info(
            "SESSION_SNAPSHOT | timestamp=%s phase=%s dte=%s tags=%s",
            snapshot.timestamp.isoformat(),
            snapshot.session_phase,
            snapshot.days_to_expiry,
            ",".join(day_context.tags),
        )
        return snapshot


def build_session_snapshot(
    *,
    timestamp: datetime,
    index_candle: Candle | None = None,
    futures_candle: Candle | None = None,
    session_candles: Sequence[Candle] = (),
    prior_day_candles: Sequence[Candle] = (),
    calendar: MarketCalendar | None = None,
    opening_range_minutes: int | None = None,
) -> SessionSnapshot:
    """Convenience wrapper for one-shot snapshot construction."""
    engine = SessionFeatureEngine(
        calendar=calendar,
        opening_range_minutes=opening_range_minutes,
    )
    return engine.build_session_snapshot(
        timestamp=timestamp,
        index_candle=index_candle,
        futures_candle=futures_candle,
        session_candles=session_candles,
        prior_day_candles=prior_day_candles,
    )
