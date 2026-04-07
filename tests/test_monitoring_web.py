from __future__ import annotations

import csv
import json
from pathlib import Path

from monitoring_web import build_dashboard_payload, render_index


def test_render_index_includes_favicon_reference() -> None:
    html = render_index()

    assert 'rel="icon"' in html
    assert 'favicon.ico' in html


def test_build_dashboard_payload_reads_latest_summary_and_records(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    records_dir = tmp_path / "records"
    reports_dir.mkdir(parents=True)
    records_dir.mkdir(parents=True)

    summary_path = reports_dir / "trade_summary_2026-04-06.json"
    summary_path.write_text(
        json.dumps(
            {
                "session_date": "2026-04-06",
                "total_trades": 3,
                "gross_pnl": 0.0,
                "fees_and_costs": 0.0,
                "net_pnl": 0.0,
                "by_state": {"Expiry Compression": {"count": 3, "net_pnl": 0.0}},
                "by_playbook": {"iron_condor": {"count": 3, "net_pnl": 0.0}},
            }
        ),
        encoding="utf-8",
    )

    records_path = records_dir / "trade_records_2026-04-06.csv"
    with records_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "trade_id",
                "state_at_entry",
                "playbook",
                "structure_type",
                "net_pnl",
                "session_date",
                "underlying_context",
                "expiry",
                "strike_or_strikes",
                "side",
                "quantity",
                "entry_price_or_prices",
                "exit_price_or_prices",
                "exit_reason",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "trade_id": "paper-1",
                "state_at_entry": "Expiry Compression",
                "playbook": "iron_condor",
                "structure_type": "iron_condor",
                "net_pnl": "0.0",
                "session_date": "2026-04-06",
                "underlying_context": json.dumps({"paper_mode": True, "underlying_price": 22880.0}),
                "expiry": "same_week",
                "strike_or_strikes": json.dumps([22700.0, 22800.0, 23000.0, 23100.0]),
                "side": "PAPER",
                "quantity": "1",
                "entry_price_or_prices": json.dumps([95.0]),
                "exit_price_or_prices": json.dumps([]),
                "exit_reason": "paper_eval_signal",
            }
        )

    payload = build_dashboard_payload(tmp_path)

    assert payload["session_date"] == "2026-04-06"
    assert payload["summary"]["total_trades"] == 3
    assert payload["recent_records"][0]["trade_id"] == "paper-1"
    assert payload["status"]["mode"] == "paper"
    assert payload["latest_signal"]["state"] == "Expiry Compression"
    assert payload["latest_signal"]["display_trade_id"] == "1"
    assert payload["latest_signal"]["display_playbook"] == "Iron Condor"
    assert payload["latest_signal"]["display_expiry"] == "07 Apr 2026"
    assert payload["headline"]["current_playbook"] == "iron_condor"
    assert payload["headline"]["status_text"] == "Watching for setup"
    assert payload["trade_strip"]["status"] == "WATCHING"
    assert payload["trade_strip"]["last_exit_reason"] == "No exits yet"
    assert payload["pnl_status"]["live"] is False
    assert payload["pnl_status"]["mode"] == "signal_only"
    assert payload["ops"]["control_mode"] == "terminal_or_systemd"
    assert payload["ops"]["public_controls_enabled"] is False


def test_build_dashboard_payload_reads_live_mtm_file_when_present(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    records_dir = tmp_path / "records"
    reports_dir.mkdir(parents=True)
    records_dir.mkdir(parents=True)

    (reports_dir / "live_paper_mtm.json").write_text(
        json.dumps(
            {
                "live": True,
                "trade_id": "paper-99",
                "playbook": "iron_condor",
                "entry_credit": 37.0,
                "current_close_value": 30.0,
                "mtm_points": 7.0,
                "unrealised_pnl": 350.0,
                "underlying_price": 22895.0,
                "last_update": "2026-04-06T14:35:00+05:30",
            }
        ),
        encoding="utf-8",
    )

    payload = build_dashboard_payload(tmp_path)

    assert payload["pnl_status"]["live"] is True
    assert payload["pnl_status"]["mode"] == "live_mtm"
    assert payload["pnl_status"]["unrealised_pnl"] == 350.0
    assert payload["pnl_status"]["realised_pnl_today"] == 0.0
    assert payload["pnl_status"]["underlying_price"] == 22895.0
    assert payload["trade_strip"]["status"] == "OPEN"
    assert payload["closed_trades"] == []
