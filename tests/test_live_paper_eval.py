from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.run_paper_live_eval import TradeStateGate, StreamHealthMonitor, _load_recent_underlying_price, build_option_subscription_basket
from scripts.run_research import evaluate_completed_candles
from scripts.schema import Candle, MarketInstrument, MarketTick


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


def test_build_option_subscription_basket_targets_single_expected_expiry(monkeypatch) -> None:
    calls: list[tuple[float, str, int]] = []

    def fake_resolve(*, center_price: float, expiry_hint: str, as_of: date, breadth_steps: int):
        calls.append((center_price, expiry_hint, breadth_steps))
        return [
            MarketInstrument(
                name=f"{expiry_hint}-instrument",
                exchange_segment="NSE_FNO",
                security_id="202",
                instrument_type="OPTION",
            )
        ]

    monkeypatch.setattr("scripts.run_paper_live_eval.resolve_nifty_option_basket", fake_resolve)

    instruments = build_option_subscription_basket(center_price=23950.0, as_of=date(2026, 4, 8), prior_day_candles=[])

    assert calls == [(23950.0, "next_week", 10)]
    assert [instrument.security_id for instrument in instruments] == ["202"]


def test_load_recent_underlying_price_prefers_latest_historical_record_when_session_has_no_data(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    records_dir = data_dir / "records"
    records_dir.mkdir(parents=True)

    current_session = records_dir / "trade_records_2026-04-09.csv"
    with current_session.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["underlying_context"])
        writer.writeheader()

    previous_session = records_dir / "trade_records_2026-04-08.csv"
    with previous_session.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["underlying_context"])
        writer.writeheader()
        writer.writerow({"underlying_context": json.dumps({"underlying_price": 23956.1})})

    monkeypatch.setattr("scripts.run_paper_live_eval.DATA_DIR", data_dir)

    assert _load_recent_underlying_price(session_date=date(2026, 4, 9)) == 23956.1


def test_stream_health_monitor_warns_when_index_ticks_stop(caplog) -> None:
    monitor = StreamHealthMonitor(stall_after_seconds=90, warn_repeat_seconds=120, log_every_ticks=10_000)
    option = MarketInstrument(
        name="NIFTY 26 MAY 23850 PUT",
        exchange_segment="NSE_FNO",
        security_id="72174",
        instrument_type="OPTION",
    )

    index_tick = MarketTick(
        instrument=INDEX,
        timestamp=datetime(2026, 4, 9, 10, 27, 0, tzinfo=TZ),
        ltp=23830.0,
    )
    option_tick = MarketTick(
        instrument=option,
        timestamp=datetime(2026, 4, 9, 10, 28, 31, tzinfo=TZ),
        ltp=537.0,
    )

    with caplog.at_level("WARNING"):
        monitor.observe_tick(index_tick)
        monitor.observe_tick(option_tick)
        monitor.maybe_log(tick_counter=2, decision_counter=6, current_tick=option_tick)

    assert "PAPER_EVAL_INDEX_STALLED" in caplog.text
    assert "missing_for_seconds=91.0" in caplog.text
