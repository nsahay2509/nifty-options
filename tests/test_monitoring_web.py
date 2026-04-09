from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path

import monitoring_web
from monitoring_web import build_dashboard_payload, render_index


def test_render_index_includes_favicon_reference() -> None:
    html = render_index()

    assert 'rel="icon"' in html
    assert 'favicon.ico' in html
    assert 'System Status' in html
    assert 'Portfolio' in html
    assert 'Open Positions' in html
    assert 'Alerts' in html
    assert 'id="alerts-list"' in html
    assert 'href="/config"' in html
    assert 'Confirmation gate' in html
    assert 'id="confirmation-gate"' in html
    assert 'State since morning' in html
    assert 'id="state-history"' in html
    assert 'Decision criteria' in html
    assert 'id="decision-criteria"' in html
    assert 'Simple trade view' in html
    assert 'id="simple-status"' in html


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
    expected_entry = monitoring_web.APP_CONFIG.trading.entry_confirmations_required
    assert "1-minute" in payload["trade_strip"]["status_note"]
    assert str(expected_entry) in payload["trade_strip"]["status_note"]
    assert payload["trade_strip"]["last_exit_reason"] == "No current-session closure yet"
    assert payload["confirmation_gate"]["entry_confirmations_required"] == monitoring_web.APP_CONFIG.trading.entry_confirmations_required
    assert payload["confirmation_gate"]["exit_confirmations_required"] == monitoring_web.APP_CONFIG.trading.exit_confirmations_required
    assert payload["pnl_status"]["live"] is False
    assert payload["pnl_status"]["mode"] == "signal_only"
    assert payload["ops"]["control_mode"] == "terminal_or_systemd"
    assert payload["ops"]["public_controls_enabled"] is False
    assert payload["status"]["runtime_service_name"] == monitoring_web.AUTO_PAPER_SYSTEMD_UNIT
    assert payload["status"]["runtime_service_state"] in {"UNKNOWN", "ACTIVE", "INACTIVE", "FAILED", "ACTIVATING"}


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
    assert payload["simple_status"]["trade_happening_now"] == "Yes"
    assert payload["closed_trades"] == []


def test_build_dashboard_payload_marks_pending_trade_as_entered(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    records_dir = tmp_path / "records"
    reports_dir.mkdir(parents=True)
    records_dir.mkdir(parents=True)

    (reports_dir / "trade_summary_2026-04-08.json").write_text(
        json.dumps(
            {
                "session_date": "2026-04-08",
                "total_trades": 7,
                "gross_pnl": 0.0,
                "fees_and_costs": 0.0,
                "net_pnl": 0.0,
                "by_state": {"Controlled Range": {"count": 7, "net_pnl": 0.0}},
                "by_playbook": {"call_or_put_credit_spread": {"count": 7, "net_pnl": 0.0}},
            }
        ),
        encoding="utf-8",
    )

    records_path = records_dir / "trade_records_2026-04-08.csv"
    with records_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "trade_id",
                "status",
                "opened_at",
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
                "option_types",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "trade_id": "paper-older",
                "status": "OPEN",
                "opened_at": "2026-04-08T12:30:00+05:30",
                "state_at_entry": "Controlled Range",
                "playbook": "call_or_put_credit_spread",
                "structure_type": "call_or_put_credit_spread",
                "net_pnl": "0.0",
                "session_date": "2026-04-08",
                "underlying_context": json.dumps({"paper_mode": True, "underlying_price": 23920.0}),
                "expiry": "next_week",
                "strike_or_strikes": json.dumps([23800.0, 23900.0]),
                "side": "PAPER",
                "quantity": "1",
                "entry_price_or_prices": json.dumps([65.0]),
                "exit_price_or_prices": json.dumps([]),
                "exit_reason": "paper_eval_signal",
                "option_types": json.dumps(["PE"]),
            }
        )
        writer.writerow(
            {
                "trade_id": "paper-123",
                "status": "OPEN",
                "opened_at": "2026-04-08T12:35:00+05:30",
                "state_at_entry": "Controlled Range",
                "playbook": "call_or_put_credit_spread",
                "structure_type": "call_or_put_credit_spread",
                "net_pnl": "0.0",
                "session_date": "2026-04-08",
                "underlying_context": json.dumps({"paper_mode": True, "underlying_price": 23950.0}),
                "expiry": "next_week",
                "strike_or_strikes": json.dumps([23850.0, 23950.0]),
                "side": "PAPER",
                "quantity": "1",
                "entry_price_or_prices": json.dumps([65.0]),
                "exit_price_or_prices": json.dumps([]),
                "exit_reason": "paper_eval_signal",
                "option_types": json.dumps(["PE"]),
            }
        )

    (reports_dir / "live_paper_mtm.json").write_text(
        json.dumps(
            {
                "live": False,
                "mode": "awaiting_option_ticks",
                "trade_id": "paper-123",
                "session_date": "2026-04-08",
                "playbook": "call_or_put_credit_spread",
                "reason": "Waiting for live ticks on all required option legs.",
                "last_update": "2026-04-08T12:35:00+05:30",
            }
        ),
        encoding="utf-8",
    )

    payload = build_dashboard_payload(tmp_path)

    assert payload["headline"]["status_text"] == "Trade entered"
    assert payload["trade_strip"]["status"] == "ENTERED"
    assert payload["simple_status"]["trade_happening_now"] == "Yes"
    assert len(payload["open_positions"]) == 1
    assert payload["open_positions"][0]["trade_id"] == "paper-123"
    assert payload["open_positions"][0]["display_option_types"] == "PE"
    assert "23850 pe buy" in payload["open_positions"][0]["display_strikes"].lower()
    assert "23950 pe sell" in payload["open_positions"][0]["display_strikes"].lower()
    assert "waiting for option prices" in payload["simple_status"]["progress_summary"].lower()


def test_build_dashboard_payload_filters_booked_pnl_to_displayed_session_and_marks_signal_only_closures(tmp_path: Path, monkeypatch) -> None:
    reports_dir = tmp_path / "reports"
    records_dir = tmp_path / "records"
    reports_dir.mkdir(parents=True)
    records_dir.mkdir(parents=True)

    (reports_dir / "trade_summary_2026-04-08.json").write_text(
        json.dumps(
            {
                "session_date": "2026-04-08",
                "total_trades": 12,
                "gross_pnl": 0.0,
                "fees_and_costs": 0.0,
                "net_pnl": 0.0,
                "by_state": {"Gap Mean Reversion": {"count": 3, "net_pnl": 0.0}},
                "by_playbook": {"reversal_debit_spread": {"count": 3, "net_pnl": 0.0}},
            }
        ),
        encoding="utf-8",
    )

    live_mtm_path = reports_dir / "live_paper_mtm.json"
    live_mtm_path.write_text(
        json.dumps(
            {
                "live": False,
                "mode": "waiting_for_trade",
                "realised_pnl_today": 11570.0,
                "closed_trade_count": 84,
                "reason": "Last paper trade was closed: no_trade_signal.",
                "recent_closed": [
                    {
                        "trade_id": "paper-20260408-0952-38",
                        "playbook": "reversal_debit_spread",
                        "structure_type": "reversal_debit_spread",
                        "exit_reason": "no_trade_signal",
                        "closed_at": "2026-04-08T04:24:01.000548+00:00",
                        "mtm_points": 0.0,
                        "realised_pnl": 0.0,
                    },
                    {
                        "trade_id": "paper-20260407-1520-366",
                        "playbook": "expiry_directional_scalp",
                        "structure_type": "expiry_directional_scalp",
                        "exit_reason": "session_end",
                        "closed_at": "2026-04-07T10:00:00.031283+00:00",
                        "mtm_points": 2.1,
                        "realised_pnl": 136.5,
                    },
                ],
                "last_update": "2026-04-08T04:24:01.000548+00:00",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(monitoring_web, "RUNTIME_LOG_PATH", tmp_path / "missing_runtime.log")

    payload = build_dashboard_payload(tmp_path)

    assert payload["trade_strip"]["status"] == "WATCHING"
    assert payload["pnl_status"]["realised_pnl_today"] == 0.0
    assert payload["pnl_status"]["closed_trade_count"] == 1
    assert payload["pnl_status"]["booked_trade_count"] == 0
    assert payload["pnl_status"]["signal_only_count"] == 1
    assert payload["signal_only_closed_trades"][0]["display_activity_type"] == "Signal-only closure"
    assert payload["signal_only_closed_trades"][0]["display_reason"] == "No trade signal"
    assert payload["closed_trades"] == []

    old_ts = time.time() - 600
    os.utime(live_mtm_path, (old_ts, old_ts))
    os.utime(reports_dir / "trade_summary_2026-04-08.json", (old_ts, old_ts))
    payload_after_stale = build_dashboard_payload(tmp_path)
    assert payload_after_stale["trade_strip"]["status"] in {"STALE", "STOPPED"}


def test_build_dashboard_payload_uses_runtime_heartbeat_to_avoid_false_stale(tmp_path: Path, monkeypatch) -> None:
    reports_dir = tmp_path / "reports"
    records_dir = tmp_path / "records"
    reports_dir.mkdir(parents=True)
    records_dir.mkdir(parents=True)

    summary_path = reports_dir / "trade_summary_2026-04-08.json"
    summary_path.write_text(
        json.dumps(
            {
                "session_date": "2026-04-08",
                "total_trades": 0,
                "gross_pnl": 0.0,
                "fees_and_costs": 0.0,
                "net_pnl": 0.0,
                "by_state": {},
                "by_playbook": {},
            }
        ),
        encoding="utf-8",
    )

    stale_ts = time.time() - 600
    os.utime(summary_path, (stale_ts, stale_ts))

    runtime_log = tmp_path / "nifty_rebuild.log"
    fresh_log_ts = datetime.now(monitoring_web.MarketCalendar().timezone).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    runtime_log.write_text(
        f"{fresh_log_ts} | run_paper_live_eval | INFO | PAPER_EVAL_RESULT | state=Choppy Transition playbook=no_trade structure=no_trade no_trade=True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(monitoring_web, "RUNTIME_LOG_PATH", runtime_log)

    payload = build_dashboard_payload(tmp_path)

    assert payload["status"]["runtime_status"] == "LIVE"
    assert payload["headline"]["status_text"] == "Watching for setup"
    assert payload["trade_strip"]["status"] == "WATCHING"


def test_build_dashboard_payload_marks_service_backed_runtime_as_stale_not_stopped(tmp_path: Path, monkeypatch) -> None:
    reports_dir = tmp_path / "reports"
    records_dir = tmp_path / "records"
    reports_dir.mkdir(parents=True)
    records_dir.mkdir(parents=True)

    summary_path = reports_dir / "trade_summary_2026-04-08.json"
    summary_path.write_text(
        json.dumps(
            {
                "session_date": "2026-04-08",
                "total_trades": 0,
                "gross_pnl": 0.0,
                "fees_and_costs": 0.0,
                "net_pnl": 0.0,
                "by_state": {},
                "by_playbook": {},
            }
        ),
        encoding="utf-8",
    )
    stale_ts = time.time() - 600
    os.utime(summary_path, (stale_ts, stale_ts))

    monkeypatch.setattr(
        monitoring_web,
        "get_systemd_unit_state",
        lambda unit_name: {
            "unit": unit_name,
            "active_state": "active",
            "sub_state": "running",
            "load_state": "loaded",
            "unit_file_state": "enabled",
            "running": True,
            "available": True,
        },
    )
    monkeypatch.setattr(monitoring_web, "RUNTIME_LOG_PATH", tmp_path / "missing_runtime.log")

    payload = build_dashboard_payload(tmp_path)

    assert payload["status"]["runtime_status"] == "STALE"
    assert payload["status"]["runtime_service_running"] is True
    assert payload["status"]["runtime_service_state"] == "ACTIVE"
    assert any("still running in systemd" in alert for alert in payload["alerts"])


def test_build_dashboard_payload_hides_inconsistent_carried_totals_even_when_live_mtm_session_matches(tmp_path: Path, monkeypatch) -> None:
    reports_dir = tmp_path / "reports"
    records_dir = tmp_path / "records"
    reports_dir.mkdir(parents=True)
    records_dir.mkdir(parents=True)

    (reports_dir / "trade_summary_2026-04-08.json").write_text(
        json.dumps(
            {
                "session_date": "2026-04-08",
                "total_trades": 8,
                "gross_pnl": 0.0,
                "fees_and_costs": 0.0,
                "net_pnl": 0.0,
                "by_state": {"Gap Mean Reversion": {"count": 8, "net_pnl": 0.0}},
                "by_playbook": {"reversal_debit_spread": {"count": 8, "net_pnl": 0.0}},
            }
        ),
        encoding="utf-8",
    )

    (reports_dir / "live_paper_mtm.json").write_text(
        json.dumps(
            {
                "live": False,
                "mode": "awaiting_option_ticks",
                "session_date": "2026-04-08",
                "realised_pnl_today": 11570.0,
                "closed_trade_count": 103,
                "reason": "Waiting for live ticks on all required option legs.",
                "recent_closed": [
                    {
                        "trade_id": "paper-20260408-1156-162",
                        "playbook": "reversal_debit_spread",
                        "structure_type": "reversal_debit_spread",
                        "exit_reason": "no_trade_signal",
                        "closed_at": "2026-04-08T06:28:00.511128+00:00",
                        "mtm_points": 0.0,
                        "realised_pnl": 0.0,
                    },
                    {
                        "trade_id": "paper-20260408-1154-160",
                        "playbook": "reversal_debit_spread",
                        "structure_type": "reversal_debit_spread",
                        "exit_reason": "structure_change",
                        "closed_at": "2026-04-08T06:26:00.494503+00:00",
                        "mtm_points": 0.0,
                        "realised_pnl": 0.0,
                    },
                ],
                "last_update": "2026-04-08T06:28:00.511128+00:00",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(monitoring_web, "RUNTIME_LOG_PATH", tmp_path / "missing_runtime.log")

    payload = build_dashboard_payload(tmp_path)

    assert payload["pnl_status"]["realised_pnl_today"] == 0.0
    assert payload["pnl_status"]["closed_trade_count"] == 2
    assert payload["trade_strip"]["closed_trade_count"] == 2
    assert "carried-over" in payload["pnl_status"]["reason"].lower()


def test_build_dashboard_payload_includes_state_history_since_morning(tmp_path: Path, monkeypatch) -> None:
    reports_dir = tmp_path / "reports"
    records_dir = tmp_path / "records"
    reports_dir.mkdir(parents=True)
    records_dir.mkdir(parents=True)

    (reports_dir / "trade_summary_2026-04-08.json").write_text(
        json.dumps(
            {
                "session_date": "2026-04-08",
                "total_trades": 0,
                "gross_pnl": 0.0,
                "fees_and_costs": 0.0,
                "net_pnl": 0.0,
                "by_state": {},
                "by_playbook": {},
            }
        ),
        encoding="utf-8",
    )

    runtime_log = tmp_path / "nifty_rebuild.log"
    runtime_log.write_text(
        "2026-04-08 09:16:00,557 | state_engine | INFO | STATE | state=Controlled Range confidence=high tradeable=True ambiguity=none evidence={'session_phase': 'opening_range'}\n"
        "2026-04-08 09:17:00,059 | state_engine | INFO | STATE | state=Choppy Transition confidence=medium tradeable=False ambiguity=mixed_structure evidence={'current_price': 23918.0, 'prior_close': 23918.0, 'session_open': 23875.94921875, 'gap_pct': -0.001758, 'realized_range_pct': 0.003614, 'distance_to_mid_pct': 0.001552, 'close_location': 0.9294, 'days_to_expiry': 5, 'session_phase': 'opening_range'}\n"
        "2026-04-08 09:17:00,060 | edge_filter | INFO | EDGE | playbook=no_trade no_trade=True reason=state_marked_untradeable alternatives=wait\n"
        "2026-04-08 09:17:00,061 | playbook_selector | INFO | PLAYBOOK | selected=no_trade no_trade=True reason=state_marked_untradeable alternatives=wait\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(monitoring_web, "RUNTIME_LOG_PATH", runtime_log)

    payload = build_dashboard_payload(tmp_path)

    assert payload["state_history"]["entry_count"] == 2
    assert payload["state_history"]["entries"][0]["state"] == "Controlled Range"
    assert payload["state_history"]["entries"][1]["state"] == "Choppy Transition"
    assert payload["state_history"]["counts"]["Controlled Range"] == 1
    assert payload["decision_context"]["state"] == "Choppy Transition"
    assert payload["decision_context"]["edge_reason"] == "state_marked_untradeable"
    assert payload["decision_context"]["no_trade"] is True
    assert payload["decision_context"]["criteria_checks"][0]["label"] == "Gap filter"
