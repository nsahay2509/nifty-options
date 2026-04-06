from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from scripts.paper_mtm import PaperMtmTracker
from scripts.schema import MarketInstrument, MarketTick, StructureProposal


def _option(security_id: str, strike: float, option_type: str) -> MarketInstrument:
    return MarketInstrument(
        name=f"NIFTY_{strike}_{option_type}",
        exchange_segment="NSE_FNO",
        security_id=security_id,
        instrument_type="OPTION",
        expiry="2026-04-07",
        strike=strike,
        option_type=option_type,
        lot_size=50,
    )


def test_paper_mtm_tracker_marks_iron_condor_live_and_writes_snapshot(tmp_path: Path) -> None:
    instruments = {
        (22700.0, "PE"): _option("1001", 22700.0, "PE"),
        (22800.0, "PE"): _option("1002", 22800.0, "PE"),
        (23000.0, "CE"): _option("1003", 23000.0, "CE"),
        (23100.0, "CE"): _option("1004", 23100.0, "CE"),
    }

    tracker = PaperMtmTracker(
        output_file=tmp_path / "live_paper_mtm.json",
        instrument_lookup=lambda *, strike, option_type, expiry_hint, as_of: instruments[(strike, option_type)],
    )
    structure = StructureProposal(
        structure_type="iron_condor",
        expiry="same_week",
        strikes=(22700.0, 22800.0, 23000.0, 23100.0),
        estimated_premium=95.0,
    )

    tracker.activate_position(
        trade_id="paper-1",
        session_date="2026-04-06",
        playbook="iron_condor",
        structure=structure,
        underlying_price=22900.0,
        quantity=1,
        as_of=date(2026, 4, 6),
    )

    entry_prices = {"1001": 20.0, "1002": 40.0, "1003": 35.0, "1004": 18.0}
    for sid, ltp in entry_prices.items():
        tracker.on_tick(
            MarketTick(
                instrument=next(inst for inst in instruments.values() if inst.security_id == sid),
                timestamp=datetime(2026, 4, 6, 9, 31, tzinfo=UTC),
                ltp=ltp,
            )
        )

    mark_prices = {"1001": 21.0, "1002": 38.0, "1003": 30.0, "1004": 17.0}
    for sid, ltp in mark_prices.items():
        tracker.on_tick(
            MarketTick(
                instrument=next(inst for inst in instruments.values() if inst.security_id == sid),
                timestamp=datetime(2026, 4, 6, 9, 32, tzinfo=UTC),
                ltp=ltp,
            )
        )

    snapshot = tracker.snapshot()

    assert snapshot["live"] is True
    assert snapshot["playbook"] == "iron_condor"
    assert snapshot["entry_credit"] == 37.0
    assert snapshot["current_close_value"] == 30.0
    assert snapshot["mtm_points"] == 7.0
    assert snapshot["unrealised_pnl"] == 350.0
    assert (tmp_path / "live_paper_mtm.json").exists()


def test_paper_mtm_tracker_books_realised_pnl_when_closed(tmp_path: Path) -> None:
    instruments = {
        (22700.0, "PE"): _option("1001", 22700.0, "PE"),
        (22800.0, "PE"): _option("1002", 22800.0, "PE"),
        (23000.0, "CE"): _option("1003", 23000.0, "CE"),
        (23100.0, "CE"): _option("1004", 23100.0, "CE"),
    }

    tracker = PaperMtmTracker(
        output_file=tmp_path / "live_paper_mtm.json",
        instrument_lookup=lambda *, strike, option_type, expiry_hint, as_of: instruments[(strike, option_type)],
    )
    structure = StructureProposal(
        structure_type="iron_condor",
        expiry="same_week",
        strikes=(22700.0, 22800.0, 23000.0, 23100.0),
        estimated_premium=95.0,
    )
    tracker.activate_position(
        trade_id="paper-2",
        session_date="2026-04-06",
        playbook="iron_condor",
        structure=structure,
        underlying_price=22900.0,
        quantity=1,
        as_of=date(2026, 4, 6),
    )

    for sid, ltp in {"1001": 20.0, "1002": 40.0, "1003": 35.0, "1004": 18.0}.items():
        tracker.on_tick(
            MarketTick(
                instrument=next(inst for inst in instruments.values() if inst.security_id == sid),
                timestamp=datetime(2026, 4, 6, 9, 31, tzinfo=UTC),
                ltp=ltp,
            )
        )
    for sid, ltp in {"1001": 21.0, "1002": 38.0, "1003": 30.0, "1004": 17.0}.items():
        tracker.on_tick(
            MarketTick(
                instrument=next(inst for inst in instruments.values() if inst.security_id == sid),
                timestamp=datetime(2026, 4, 6, 9, 32, tzinfo=UTC),
                ltp=ltp,
            )
        )

    tracker.close_active_position(reason="signal_flip")
    snapshot = tracker.snapshot()

    assert snapshot["live"] is False
    assert snapshot["realised_pnl_today"] == 350.0
    assert snapshot["closed_trade_count"] == 1
    assert snapshot["recent_closed"][0]["exit_reason"] == "signal_flip"
