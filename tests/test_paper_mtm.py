from __future__ import annotations

import json
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


def test_paper_mtm_tracker_prefers_option_mid_price_when_bid_ask_available(tmp_path: Path) -> None:
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
        trade_id="paper-mid",
        session_date="2026-04-06",
        playbook="iron_condor",
        structure=structure,
        underlying_price=22900.0,
        quantity=1,
        as_of=date(2026, 4, 6),
    )

    tracker.on_tick(
        MarketTick(
            instrument=instruments[(22700.0, "PE")],
            timestamp=datetime(2026, 4, 6, 9, 31, tzinfo=UTC),
            ltp=20.0,
            best_bid_price=19.0,
            best_ask_price=21.0,
        )
    )
    tracker.on_tick(
        MarketTick(
            instrument=instruments[(22800.0, "PE")],
            timestamp=datetime(2026, 4, 6, 9, 31, tzinfo=UTC),
            ltp=40.0,
            best_bid_price=39.0,
            best_ask_price=41.0,
        )
    )
    tracker.on_tick(
        MarketTick(
            instrument=instruments[(23000.0, "CE")],
            timestamp=datetime(2026, 4, 6, 9, 31, tzinfo=UTC),
            ltp=35.0,
            best_bid_price=34.0,
            best_ask_price=36.0,
        )
    )
    tracker.on_tick(
        MarketTick(
            instrument=instruments[(23100.0, "CE")],
            timestamp=datetime(2026, 4, 6, 9, 31, tzinfo=UTC),
            ltp=18.0,
            best_bid_price=17.0,
            best_ask_price=19.0,
        )
    )

    tracker.on_tick(
        MarketTick(
            instrument=instruments[(22700.0, "PE")],
            timestamp=datetime(2026, 4, 6, 9, 32, tzinfo=UTC),
            ltp=20.0,
            best_bid_price=20.0,
            best_ask_price=22.0,
        )
    )

    snapshot = tracker.snapshot()

    assert snapshot["live"] is True
    assert snapshot["legs"][0]["entry_price"] == 20.0
    assert snapshot["legs"][0]["last_price"] == 21.0
    assert snapshot["mtm_points"] == 1.0
    assert snapshot["unrealised_pnl"] == 50.0


def test_paper_mtm_tracker_resets_realised_pnl_on_new_session(tmp_path: Path) -> None:
    output_file = tmp_path / "live_paper_mtm.json"
    output_file.write_text(
        json.dumps(
            {
                "session_date": "2026-04-06",
                "realised_pnl_today": -679.25,
                "closed_trade_count": 6,
                "recent_closed": [{"trade_id": "paper-20260406-1511-15", "realised_pnl": -172.25}],
                "reason": "Last paper trade was closed: no_trade_signal.",
                "last_update": "2026-04-06T15:18:00+05:30",
            }
        ),
        encoding="utf-8",
    )

    tracker = PaperMtmTracker(output_file=output_file, session_date="2026-04-07")
    snapshot = tracker.snapshot()

    assert snapshot["session_date"] == "2026-04-07"
    assert snapshot["realised_pnl_today"] == 0.0
    assert snapshot["closed_trade_count"] == 0
    assert snapshot["recent_closed"] == []


def test_paper_mtm_tracker_resets_carryover_when_new_trade_starts_on_next_session(tmp_path: Path) -> None:
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
    tracker.close_active_position(reason="session_end")

    tracker.activate_position(
        trade_id="paper-3",
        session_date="2026-04-07",
        playbook="iron_condor",
        structure=structure,
        underlying_price=22940.0,
        quantity=1,
        as_of=date(2026, 4, 7),
    )
    snapshot = tracker.snapshot()

    assert snapshot["session_date"] == "2026-04-07"
    assert snapshot["realised_pnl_today"] == 0.0
    assert snapshot["closed_trade_count"] == 0
    assert snapshot["recent_closed"] == []


def test_paper_mtm_tracker_restores_active_trade_for_same_session(tmp_path: Path) -> None:
    output_file = tmp_path / "live_paper_mtm.json"
    output_file.write_text(
        json.dumps(
            {
                "live": True,
                "mode": "live_mtm",
                "reason": "Active paper trade preserved for in-session restart.",
                "trade_id": "paper-20260409-1021-1",
                "last_signal_id": "paper-20260409-1021-1",
                "session_date": "2026-04-09",
                "playbook": "call_or_put_credit_spread",
                "structure_type": "call_or_put_credit_spread",
                "expiry": "next_week",
                "strikes": [23750.0, 23850.0],
                "entry_credit": 15.55,
                "entry_debit": 0.0,
                "current_close_value": 15.65,
                "mtm_points": -0.1,
                "unrealised_pnl": -6.5,
                "realised_pnl_today": 0.0,
                "closed_trade_count": 6,
                "recent_closed": [],
                "underlying_price": 23830.6,
                "last_update": "2026-04-09T10:27:24+05:30",
                "legs": [
                    {
                        "security_id": "72170",
                        "symbol": "NIFTY 26 MAY 23750 PUT",
                        "strike": 23750.0,
                        "option_type": "PE",
                        "side": "BUY",
                        "quantity": 1,
                        "lot_size": 65,
                        "entry_price": 535.45,
                        "last_price": 535.45,
                    },
                    {
                        "security_id": "72174",
                        "symbol": "NIFTY 26 MAY 23850 PUT",
                        "strike": 23850.0,
                        "option_type": "PE",
                        "side": "SELL",
                        "quantity": 1,
                        "lot_size": 65,
                        "entry_price": 551.0,
                        "last_price": 551.1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    tracker = PaperMtmTracker(
        output_file=output_file,
        session_date="2026-04-09",
        instrument_lookup=lambda *, strike, option_type, expiry_hint, as_of: _option(
            "72170" if strike == 23750.0 else "72174",
            strike,
            option_type,
        ),
    )
    snapshot = tracker.snapshot()

    assert snapshot["live"] is True
    assert snapshot["trade_id"] == "paper-20260409-1021-1"
    assert snapshot["mtm_points"] == -0.1
    assert len(snapshot["legs"]) == 2
