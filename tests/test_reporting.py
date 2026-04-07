from __future__ import annotations

from pathlib import Path

from scripts.reporting import ReportingService
from scripts.schema import StructureProposal, TradeRecord
from scripts.trade_recorder import TradeRecorder


def _write_sample_records(base_dir: Path) -> Path:
    recorder = TradeRecorder(base_dir=base_dir)

    record_1 = TradeRecord(
        trade_id="trade-001",
        state_at_entry="Trend Continuation",
        playbook="bull_call_spread_or_bear_put_spread",
        structure_type="bull_call_spread_or_bear_put_spread",
        gross_pnl=250.0,
        fees_and_costs=25.0,
        net_pnl=225.0,
    )
    recorder.append_trade_record(
        record_1,
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

    record_2 = recorder.build_trade_record(
        trade_id="trade-002",
        state_at_entry="Controlled Range",
        playbook="iron_condor",
        structure=StructureProposal(
            structure_type="iron_condor",
            expiry="same_day",
            strikes=(22350.0, 22450.0, 22650.0, 22750.0),
            estimated_premium=95.0,
            notes="Defined-risk range structure",
        ),
        gross_pnl=-50.0,
        fees_and_costs=20.0,
    )
    target = recorder.append_trade_record(
        record_2,
        session_date="2026-04-06",
        underlying_context={"underlying_price": 22510},
        expiry="same_day",
        strikes=(22350.0, 22450.0, 22650.0, 22750.0),
        side="SHORT",
        quantity=1,
        entry_price_or_prices=(95.0,),
        exit_price_or_prices=(145.0,),
        exit_reason="stop_hit",
    )
    return target


def test_reporting_service_summarizes_state_and_playbook_pnl(tmp_path: Path) -> None:
    target = _write_sample_records(tmp_path)
    service = ReportingService()

    summary = service.summarize_trade_file(target)

    assert summary["total_trades"] == 2
    assert summary["gross_pnl"] == 200.0
    assert summary["net_pnl"] == 155.0
    assert summary["by_state"]["Trend Continuation"]["count"] == 1
    assert summary["by_playbook"]["iron_condor"]["net_pnl"] == -70.0


def test_reporting_service_writes_json_summary_file(tmp_path: Path) -> None:
    target = _write_sample_records(tmp_path)
    service = ReportingService(output_dir=tmp_path / "reports")

    summary_path = service.write_summary(target)

    assert summary_path.exists()
    assert summary_path.name == "trade_summary_2026-04-06.json"


def test_trade_recorder_finalize_updates_csv_and_summary(tmp_path: Path) -> None:
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
        gross_pnl=0.0,
        fees_and_costs=0.0,
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
    )

    updated = recorder.finalize_trade_record(
        trade_id="trade-003",
        session_date="2026-04-07",
        gross_pnl=320.0,
        fees_and_costs=20.0,
        exit_price_or_prices=(74.9,),
        exit_reason="structure_change",
    )

    assert updated == target

    summary = ReportingService().summarize_trade_file(target)
    assert summary["gross_pnl"] == 320.0
    assert summary["fees_and_costs"] == 20.0
    assert summary["net_pnl"] == 300.0
