from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.schema import Candle, PriorDayLevels, SessionReferences, SessionSnapshot
from scripts.trade_engine import TradeEngine


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
    candle = Candle(
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
    return SessionSnapshot(
        timestamp=ts,
        index_candle=candle,
        futures_candle=None,
        prior_day_levels=PriorDayLevels(
            session_date="2026-04-05",
            open=prior_close - 40,
            high=prior_close + 50,
            low=prior_close - 80,
            close=prior_close,
            midpoint=prior_close - 15,
            range_points=130,
        ),
        session_references=SessionReferences(
            session_date="2026-04-06",
            opening_range_high=opening_range_high,
            opening_range_low=opening_range_low,
            intraday_high=intraday_high,
            intraday_low=intraday_low,
            session_midpoint=(intraday_high + intraday_low) / 2,
            realized_range=intraday_high - intraday_low,
            derived_from_interval_min=1,
        ),
        days_to_expiry=days_to_expiry,
        session_phase=session_phase,
        raw_context={"session_open": session_open},
    )


def test_trade_engine_runs_full_directional_pipeline() -> None:
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

    result = TradeEngine().evaluate(snapshot)

    assert result.state_assessment.state_name == "Trend Continuation"
    assert result.edge_decision.no_trade is False
    assert result.playbook_decision.playbook_name == "bull_call_spread_or_bear_put_spread"
    assert result.structure_proposal.structure_type == "bull_call_spread_or_bear_put_spread"


def test_trade_engine_returns_no_trade_pipeline_when_state_is_untradeable() -> None:
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

    result = TradeEngine().evaluate(snapshot)

    assert result.state_assessment.state_name == "Choppy Transition"
    assert result.edge_decision.no_trade is True
    assert result.playbook_decision.playbook_name == "no_trade"
    assert result.structure_proposal.structure_type == "no_trade"
