from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.market_calendar import MarketCalendar
from scripts.schema import Candle, MarketInstrument
from scripts.session_features import (
    SessionFeatureEngine,
    derive_prior_day_levels,
    derive_session_references,
)


TZ = ZoneInfo("Asia/Kolkata")
INSTRUMENT = MarketInstrument(
    name="NIFTY_50_INDEX",
    exchange_segment="IDX_I",
    security_id="13",
    instrument_type="INDEX",
)


def make_candle(hour: int, minute: int, open_: float, high: float, low: float, close: float) -> Candle:
    start = datetime(2026, 4, 6, hour, minute, tzinfo=TZ)
    return Candle(
        instrument=INSTRUMENT,
        interval_min=1,
        start=start,
        end=start.replace(minute=start.minute + 1),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100,
        tick_count=5,
    )


def test_derive_prior_day_levels_from_candles() -> None:
    candles = [
        make_candle(9, 15, 22500, 22520, 22490, 22510),
        make_candle(9, 16, 22510, 22540, 22500, 22535),
        make_candle(9, 17, 22535, 22550, 22480, 22495),
    ]

    levels = derive_prior_day_levels(candles)

    assert levels.session_date == "2026-04-06"
    assert levels.open == 22500
    assert levels.high == 22550
    assert levels.low == 22480
    assert levels.close == 22495
    assert levels.midpoint == 22515
    assert levels.range_points == 70


def test_derive_session_references_tracks_opening_and_intraday_range() -> None:
    candles = [
        make_candle(9, 15, 22500, 22520, 22490, 22510),
        make_candle(9, 16, 22510, 22540, 22500, 22535),
        make_candle(9, 17, 22535, 22550, 22480, 22495),
        make_candle(9, 31, 22495, 22600, 22470, 22590),
    ]

    refs = derive_session_references(candles, opening_range_minutes=15)

    assert refs.session_date == "2026-04-06"
    assert refs.opening_range_high == 22550
    assert refs.opening_range_low == 22480
    assert refs.intraday_high == 22600
    assert refs.intraday_low == 22470
    assert refs.session_midpoint == 22535
    assert refs.realized_range == 130


def test_build_session_snapshot_includes_phase_and_expiry_context() -> None:
    prior_day = [
        make_candle(9, 15, 22300, 22340, 22290, 22330),
        make_candle(9, 16, 22330, 22360, 22310, 22350),
    ]
    session_candles = [
        make_candle(9, 15, 22500, 22520, 22490, 22510),
        make_candle(9, 16, 22510, 22540, 22500, 22535),
        make_candle(9, 17, 22535, 22550, 22480, 22495),
    ]

    engine = SessionFeatureEngine(calendar=MarketCalendar())
    snapshot = engine.build_session_snapshot(
        timestamp=datetime(2026, 4, 6, 9, 20, tzinfo=TZ),
        index_candle=session_candles[-1],
        futures_candle=None,
        session_candles=session_candles,
        prior_day_candles=prior_day,
    )

    assert snapshot.session_phase == "opening_range"
    assert snapshot.days_to_expiry == 1
    assert snapshot.prior_day_levels is not None
    assert snapshot.session_references is not None
    assert snapshot.raw_context["is_expiry_eve"] is True
    assert "expiry_eve" in snapshot.raw_context["trading_day_tags"]
