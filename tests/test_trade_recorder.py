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
    )

    assert target.exists()
    rows = list(csv.DictReader(target.open()))
    assert len(rows) == 1
    assert rows[0]["trade_id"] == "trade-001"
    assert rows[0]["state_at_entry"] == "Trend Continuation"
    assert rows[0]["net_pnl"] == "225.0"


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
