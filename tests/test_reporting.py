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


def test_reporting_service_handles_mixed_schema_trade_file(tmp_path: Path) -> None:
    target = tmp_path / "trade_records_2026-04-08.csv"
    target.write_text(
        "trade_id,state_at_entry,playbook,structure_type,gross_pnl,fees_and_costs,net_pnl,session_date,underlying_context,expiry,strike_or_strikes,side,quantity,entry_price_or_prices,exit_price_or_prices,exit_reason\n"
        "paper-legacy-1,Controlled Range,iron_condor,iron_condor,100.0,5.0,95.0,2026-04-08,\"{\"\"paper_mode\"\": true}\",same_week,\"[23800.0,23900.0]\",PAPER,1,\"[65.0]\",[],paper_eval_signal\n"
        "paper-new-2,OPEN,2026-04-08T12:24:00+05:30,,,Controlled Range,call_or_put_credit_spread,call_or_put_credit_spread,BEARISH,state_playbook_fit:Controlled Range,0.0,0.0,0.0,0.0,0.0,2026-04-08,\"{\"\"paper_mode\"\": true, \"\"underlying_price\"\": 23968.65}\",23968.65,,next_week,\"[23850.0, 23950.0]\",PAPER,1,\"[65.0]\",[],65.0,0.0,0.0,2,\"[\"\"PE\"\"]\",\"[\"\"NIFTY 26 MAY 23850 PUT\"\", \"\"NIFTY 26 MAY 23950 PUT\"\"]\",\"[{\"\"security_id\"\": \"\"72174\"\"}]\",paper_eval_signal\n",
        encoding="utf-8",
    )

    summary = ReportingService().summarize_trade_file(target)

    assert summary["total_trades"] == 2
    assert summary["gross_pnl"] == 100.0
    assert summary["fees_and_costs"] == 5.0
    assert "Controlled Range" in summary["by_state"]


def test_trade_recorder_append_normalizes_legacy_header_before_summary(tmp_path: Path) -> None:
    target = tmp_path / "trade_records_2026-04-08.csv"
    target.write_text(
        "trade_id,state_at_entry,playbook,structure_type,gross_pnl,fees_and_costs,net_pnl,session_date,underlying_context,expiry,strike_or_strikes,side,quantity,entry_price_or_prices,exit_price_or_prices,exit_reason\n"
        "paper-legacy-1,Controlled Range,iron_condor,iron_condor,100.0,5.0,95.0,2026-04-08,\"{\"\"paper_mode\"\": true}\",same_week,\"[23800.0,23900.0]\",PAPER,1,\"[65.0]\",[],paper_eval_signal\n",
        encoding="utf-8",
    )

    recorder = TradeRecorder(base_dir=tmp_path)
    record = recorder.build_trade_record(
        trade_id="trade-004",
        state_at_entry="Controlled Range",
        playbook="call_or_put_credit_spread",
        structure=StructureProposal(
            structure_type="call_or_put_credit_spread",
            expiry="next_week",
            strikes=(23850.0, 23950.0),
            estimated_premium=65.0,
        ),
        gross_pnl=0.0,
        fees_and_costs=0.0,
    )
    recorder.append_trade_record(
        record,
        session_date="2026-04-08",
        underlying_context={"paper_mode": True, "underlying_price": 23968.65},
        expiry="next_week",
        strikes=(23850.0, 23950.0),
        side="PAPER",
        quantity=1,
        entry_price_or_prices=(65.0,),
        exit_price_or_prices=(),
        exit_reason="paper_eval_signal",
        status="OPEN",
        opened_at="2026-04-08T12:24:00+05:30",
        entry_reason="state_playbook_fit:Controlled Range",
        trade_bias="BEARISH",
    )

    summary = ReportingService().summarize_trade_file(target)
    header = target.read_text(encoding="utf-8").splitlines()[0]

    assert header.startswith("trade_id,status,opened_at,closed_at,holding_minutes")
    assert summary["total_trades"] == 2
    assert summary["gross_pnl"] == 100.0
    assert summary["fees_and_costs"] == 5.0
    assert summary["by_playbook"]["call_or_put_credit_spread"]["count"] == 1
