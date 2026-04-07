from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.run_paper_live_eval import TradeStateGate
from scripts.run_research import evaluate_completed_candles
from scripts.schema import Candle, MarketInstrument


TZ = ZoneInfo("Asia/Kolkata")
INDEX = MarketInstrument(name="NIFTY_50_INDEX", exchange_segment="IDX_I", security_id="13", instrument_type="INDEX")
FUT = MarketInstrument(name="NIFTY_CURRENT_MONTH_FUT", exchange_segment="NSE_FNO", security_id="66691", instrument_type="FUTURES")


def make_candle(instrument: MarketInstrument, minute: int, close: float, high: float, low: float) -> Candle:
    start = datetime(2026, 4, 6, 10, minute, tzinfo=TZ)
    return Candle(
        instrument=instrument,
        interval_min=1,
        start=start,
        end=start.replace(minute=start.minute + 1),
        open=close - 10,
        high=high,
        low=low,
        close=close,
        volume=1000,
        tick_count=10,
    )


def test_evaluate_completed_candles_returns_trade_evaluation() -> None:
    prior_day = [make_candle(INDEX, 0, 22500, 22520, 22480)]
    session_candles = [
        make_candle(INDEX, 0, 22520, 22530, 22500),
        make_candle(INDEX, 1, 22545, 22560, 22510),
        make_candle(INDEX, 2, 22610, 22620, 22540),
    ]
    futures_candles = [make_candle(FUT, 2, 22640, 22650, 22580)]

    result = evaluate_completed_candles(
        session_candles=session_candles,
        futures_candles=futures_candles,
        prior_day_candles=prior_day,
    )

    assert result is not None
    assert result.state_assessment.tradeable is True
    assert result.structure_proposal.structure_type != "no_trade"


def test_trade_state_gate_requires_persistence_for_entry_and_switch() -> None:
    gate = TradeStateGate(entry_confirmations_required=3, exit_confirmations_required=3)

    decision_1 = gate.observe(state_name="Trend Continuation", no_trade=False)
    decision_2 = gate.observe(state_name="Trend Continuation", no_trade=False)
    decision_3 = gate.observe(state_name="Trend Continuation", no_trade=False)

    assert decision_1.action == "wait"
    assert decision_2.action == "wait"
    assert decision_3.action == "enter"
    assert decision_3.active_state == "Trend Continuation"

    switch_1 = gate.observe(state_name="Expiry Gamma Expansion", no_trade=False)
    switch_2 = gate.observe(state_name="Expiry Gamma Expansion", no_trade=False)
    switch_3 = gate.observe(state_name="Expiry Gamma Expansion", no_trade=False)

    assert switch_1.action == "hold"
    assert switch_2.action == "hold"
    assert switch_3.action == "switch"
    assert switch_3.active_state == "Expiry Gamma Expansion"


def test_trade_state_gate_exits_after_three_non_matching_states_even_without_new_entry() -> None:
    gate = TradeStateGate(entry_confirmations_required=2, exit_confirmations_required=3)

    gate.observe(state_name="Gap Continuation", no_trade=False)
    entered = gate.observe(state_name="Gap Continuation", no_trade=False)
    assert entered.action == "enter"

    mixed_1 = gate.observe(state_name="Trend Continuation", no_trade=False)
    mixed_2 = gate.observe(state_name="Controlled Range", no_trade=False)
    mixed_3 = gate.observe(state_name="Choppy Transition", no_trade=True)

    assert mixed_1.action == "hold"
    assert mixed_2.action == "hold"
    assert mixed_3.action == "exit"
    assert mixed_3.active_state == ""
