from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.schema import Candle, PriorDayLevels, SessionReferences, SessionSnapshot
from scripts.state_engine import StateEngine


TZ = ZoneInfo("Asia/Kolkata")


def make_snapshot(
    *,
    close: float,
    high: float,
    low: float,
    prior_close: float,
    session_open: float,
    opening_range_high: float,
    opening_range_low: float,
    intraday_high: float,
    intraday_low: float,
    days_to_expiry: int,
    session_phase: str = "mid_session",
) -> SessionSnapshot:
    ts = datetime(2026, 4, 6, 11, 30, tzinfo=TZ)
    index_candle = Candle(
        instrument=None,
        interval_min=1,
        start=ts,
        end=ts,
        open=session_open,
        high=high,
        low=low,
        close=close,
        volume=100,
        tick_count=5,
    )
    prior_day = PriorDayLevels(
        session_date="2026-04-05",
        open=prior_close - 40,
        high=prior_close + 50,
        low=prior_close - 80,
        close=prior_close,
        midpoint=prior_close - 15,
        range_points=130,
    )
    refs = SessionReferences(
        session_date="2026-04-06",
        opening_range_high=opening_range_high,
        opening_range_low=opening_range_low,
        intraday_high=intraday_high,
        intraday_low=intraday_low,
        session_midpoint=(intraday_high + intraday_low) / 2,
        realized_range=intraday_high - intraday_low,
        derived_from_interval_min=1,
    )
    return SessionSnapshot(
        timestamp=ts,
        index_candle=index_candle,
        futures_candle=None,
        prior_day_levels=prior_day,
        session_references=refs,
        days_to_expiry=days_to_expiry,
        session_phase=session_phase,
        raw_context={"session_open": session_open},
    )


def test_state_engine_detects_gap_continuation() -> None:
    snapshot = make_snapshot(
        close=22220,
        high=22230,
        low=22180,
        prior_close=22000,
        session_open=22120,
        opening_range_high=22190,
        opening_range_low=22100,
        intraday_high=22240,
        intraday_low=22100,
        days_to_expiry=2,
        session_phase="early_session",
    )

    assessment = StateEngine().assess(snapshot)

    assert assessment.state_name == "Gap Continuation"
    assert assessment.tradeable is True


def test_state_engine_detects_trend_continuation() -> None:
    snapshot = make_snapshot(
        close=22620,
        high=22630,
        low=22580,
        prior_close=22510,
        session_open=22520,
        opening_range_high=22540,
        opening_range_low=22500,
        intraday_high=22640,
        intraday_low=22490,
        days_to_expiry=4,
    )

    assessment = StateEngine().assess(snapshot)

    assert assessment.state_name == "Trend Continuation"
    assert assessment.tradeable is True


def test_state_engine_detects_controlled_range() -> None:
    snapshot = make_snapshot(
        close=22512,
        high=22520,
        low=22500,
        prior_close=22505,
        session_open=22508,
        opening_range_high=22525,
        opening_range_low=22490,
        intraday_high=22535,
        intraday_low=22485,
        days_to_expiry=3,
    )

    assessment = StateEngine().assess(snapshot)

    assert assessment.state_name == "Controlled Range"
    assert assessment.tradeable is True


def test_state_engine_detects_expiry_compression() -> None:
    snapshot = make_snapshot(
        close=22518,
        high=22522,
        low=22508,
        prior_close=22510,
        session_open=22512,
        opening_range_high=22525,
        opening_range_low=22500,
        intraday_high=22535,
        intraday_low=22495,
        days_to_expiry=0,
    )

    assessment = StateEngine().assess(snapshot)

    assert assessment.state_name == "Expiry Compression"
    assert assessment.tradeable is True


def test_state_engine_detects_expiry_gamma_expansion() -> None:
    snapshot = make_snapshot(
        close=22840,
        high=22860,
        low=22780,
        prior_close=22520,
        session_open=22530,
        opening_range_high=22600,
        opening_range_low=22490,
        intraday_high=22880,
        intraday_low=22480,
        days_to_expiry=0,
    )

    assessment = StateEngine().assess(snapshot)

    assert assessment.state_name == "Expiry Gamma Expansion"
    assert assessment.tradeable is True


def test_state_engine_marks_choppy_transition_as_no_trade() -> None:
    snapshot = make_snapshot(
        close=22540,
        high=22570,
        low=22510,
        prior_close=22520,
        session_open=22522,
        opening_range_high=22580,
        opening_range_low=22500,
        intraday_high=22620,
        intraday_low=22480,
        days_to_expiry=5,
    )

    assessment = StateEngine().assess(snapshot)

    assert assessment.state_name == "Choppy Transition"
    assert assessment.tradeable is False
