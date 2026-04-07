from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.schema import StructureProposal, TradeRecord
from scripts.trade_recorder import TradeRecorder


def test_trade_recorder_writes_trade_record_csv(tmp_path: Path) -> None:
    recorder = TradeRecorder(base_dir=tmp_path)
    record = TradeRecord(
        trade_id="trade-001",
        state_at_entry="Trend Continuation",
        playbook="bull_call_spread_or_bear_put_spread",
        structure_type="bull_call_spread_or_bear_put_spread",
        gross_pnl=250.0,
        fees_and_costs=25.0,
        net_pnl=225.0,
    )

    target = recorder.append_trade_record(
        record,
        session_date="2026-04-06",
        underlying_context={"underlying_price": 22540},
        expiry="same_week",
        strikes=(22550.0, 22650.0),
        side="LONG",
        quantity=1,
        entry_price_or_prices=(120.0, 40.0),
        exit_price_or_prices=(220.0, 15.0),
        exit_reason="target_hit",
        status="CLOSED",
        opened_at="2026-04-06T09:30:00+05:30",
        closed_at="2026-04-06T09:45:00+05:30",
        entry_reason="state_playbook_fit:Trend Continuation",
        entry_credit=0.0,
        entry_debit=160.0,
        exit_close_value=235.0,
        realised_pnl=225.0,
        unrealised_pnl=0.0,
        legs=[
            {
                "symbol": "NIFTY 22550 CE",
                "option_type": "CE",
                "strike": 22550.0,
                "side": "BUY",
                "quantity": 1,
                "lot_size": 50,
                "entry_price": 120.0,
                "last_price": 220.0,
            },
            {
                "symbol": "NIFTY 22650 CE",
                "option_type": "CE",
                "strike": 22650.0,
                "side": "SELL",
                "quantity": 1,
                "lot_size": 50,
                "entry_price": 40.0,
                "last_price": 15.0,
            },
        ],
    )

    assert target.exists()
    rows = list(csv.DictReader(target.open()))
    assert len(rows) == 1
    assert rows[0]["trade_id"] == "trade-001"
    assert rows[0]["state_at_entry"] == "Trend Continuation"
    assert rows[0]["net_pnl"] == "225.0"
    assert rows[0]["status"] == "CLOSED"
    assert rows[0]["opened_at"] == "2026-04-06T09:30:00+05:30"
    assert rows[0]["closed_at"] == "2026-04-06T09:45:00+05:30"
    assert rows[0]["holding_minutes"] == "15.0"
    assert rows[0]["underlying_entry_price"] == "22540.0"
    assert rows[0]["realised_pnl"] == "225.0"
    assert rows[0]["option_types"] == '["CE"]'
    assert rows[0]["leg_count"] == "2"
    assert 'NIFTY 22550 CE' in rows[0]["legs_json"]


def test_trade_recorder_builds_record_from_structure_proposal() -> None:
    recorder = TradeRecorder(base_dir=Path("/tmp"))
    proposal = StructureProposal(
        structure_type="iron_condor",
        expiry="same_day",
        strikes=(22350.0, 22450.0, 22650.0, 22750.0),
        estimated_premium=95.0,
        notes="Defined-risk range structure",
    )

    record = recorder.build_trade_record(
        trade_id="trade-002",
        state_at_entry="Expiry Compression",
        playbook="iron_condor",
        structure=proposal,
        gross_pnl=180.0,
        fees_and_costs=30.0,
    )

    assert record.trade_id == "trade-002"
    assert record.structure_type == "iron_condor"
    assert record.net_pnl == 150.0


def test_trade_recorder_finalize_adds_close_time_and_leg_details(tmp_path: Path) -> None:
    recorder = TradeRecorder(base_dir=tmp_path)
    record = recorder.build_trade_record(
        trade_id="trade-003",
        state_at_entry="Expiry Gamma Expansion",
        playbook="expiry_directional_scalp",
        structure=StructureProposal(
            structure_type="expiry_directional_scalp",
            expiry="same_day",
            strikes=(22950.0, 23000.0),
            estimated_premium=70.0,
        ),
    )

    target = recorder.append_trade_record(
        record,
        session_date="2026-04-07",
        underlying_context={"underlying_price": 22975.0},
        expiry="same_day",
        strikes=(22950.0, 23000.0),
        side="PAPER",
        quantity=1,
        entry_price_or_prices=(70.0,),
        exit_price_or_prices=(),
        exit_reason="paper_eval_signal",
        opened_at="2026-04-07T10:00:00+05:30",
        status="OPEN",
        legs=[
            {"symbol": "NIFTY 22950 CE", "option_type": "CE", "strike": 22950.0, "side": "BUY", "entry_price": 40.0},
            {"symbol": "NIFTY 23000 CE", "option_type": "CE", "strike": 23000.0, "side": "SELL", "entry_price": 20.0},
        ],
    )

    recorder.finalize_trade_record(
        trade_id="trade-003",
        session_date="2026-04-07",
        gross_pnl=130.0,
        fees_and_costs=10.0,
        exit_price_or_prices=(52.0, 18.0),
        exit_reason="structure_change",
        closed_at="2026-04-07T10:05:00+05:30",
        underlying_exit_price=23012.5,
        exit_close_value=70.0,
        legs=[
            {"symbol": "NIFTY 22950 CE", "option_type": "CE", "strike": 22950.0, "side": "BUY", "entry_price": 40.0, "last_price": 52.0},
            {"symbol": "NIFTY 23000 CE", "option_type": "CE", "strike": 23000.0, "side": "SELL", "entry_price": 20.0, "last_price": 18.0},
        ],
    )

    rows = list(csv.DictReader(target.open()))
    assert rows[0]["status"] == "CLOSED"
    assert rows[0]["closed_at"] == "2026-04-07T10:05:00+05:30"
    assert rows[0]["holding_minutes"] == "5.0"
    assert rows[0]["underlying_exit_price"] == "23012.5"
    assert rows[0]["exit_close_value"] == "70.0"
    assert rows[0]["realised_pnl"] == "130.0"
    assert '"last_price": 52.0' in rows[0]["legs_json"]
