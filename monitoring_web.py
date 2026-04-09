from __future__ import annotations

import ast
import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from scripts.config import APP_CONFIG, DATA_DIR
from scripts.market_calendar import MarketCalendar


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = DATA_DIR
DEFAULT_HOST = os.getenv("MONITOR_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MONITOR_PORT", "8010"))
FRESHNESS_SEC = int(os.getenv("MONITOR_FRESHNESS_SEC", "180"))
FAVICON_PATH = BASE_DIR / "static" / "favicon.ico"
RUNTIME_LOG_PATH = APP_CONFIG.logging.file


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def latest_matching_file(directory: Path, pattern: str) -> Path | None:
    files = sorted(directory.glob(pattern))
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def nice_label(value: str, *, default: str = "Waiting") -> str:
    if not value:
        return default
    return value.replace("_", " ").replace("-", " ").title()


def safe_json_loads(value: str, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


DISPLAY_LABELS = {
    "iron_condor": "Iron Condor",
    "bull_call_spread_or_bear_put_spread": "Directional Spread",
    "reversal_debit_spread": "Directional Spread",
    "call_or_put_credit_spread": "Credit Spread",
    "defined_risk_credit_spread": "Credit Spread",
    "long_straddle_or_strangle": "Long Straddle / Strangle",
    "expiry_directional_scalp": "Expiry Directional Scalp",
    "no_trade": "No Trade",
}

REASON_LABELS = {
    "paper_eval_signal": "Signal recorded",
    "no_trade_signal": "No trade signal",
    "structure_change": "Structure change",
    "manual_stop": "Manual stop",
    "session_end": "Session end",
}


def display_label(value: str, *, default: str = "Waiting") -> str:
    if not value:
        return default
    return DISPLAY_LABELS.get(value, nice_label(value, default=default))


def display_reason(value: str, *, default: str = "Signal recorded") -> str:
    if not value:
        return default
    return REASON_LABELS.get(value, nice_label(value, default=default))


def clean_trade_id(value: str) -> str:
    if not value:
        return ""
    return value.removeprefix("paper-")


def format_display_timestamp(value: str | float | int | None) -> str:
    if value in {None, ""}:
        return "-"
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        market_dt = dt.astimezone(MarketCalendar().timezone)
        return market_dt.strftime("%d %b %Y, %I:%M:%S %p IST")
    except Exception:
        return str(value)


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def load_runtime_heartbeat(log_path: Path | None = None) -> dict[str, object]:
    active_log_path = log_path or RUNTIME_LOG_PATH
    fallback = {"timestamp": None, "iso": "", "display": "-", "source": ""}
    if not active_log_path.exists():
        return fallback

    markers = (
        "run_paper_live_eval | INFO | PAPER_EVAL_RESULT",
        "run_paper_live_eval | INFO | PAPER_EVAL_GATE",
        "run_paper_live_eval | INFO | PAPER_EVAL_START",
        "run_paper_live_eval | INFO | PAPER_EVAL_RECORDED",
        "run_paper_live_eval | INFO | PAPER_EVAL_CLOSE_RECORDED",
    )

    try:
        with active_log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(size - 256_000, 0))
            lines = fh.read().decode("utf-8", errors="ignore").splitlines()
    except Exception:
        return fallback

    market_tz = MarketCalendar().timezone
    for line in reversed(lines):
        if not any(marker in line for marker in markers):
            continue
        try:
            dt = datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=market_tz)
        except ValueError:
            continue
        return {
            "timestamp": dt.timestamp(),
            "iso": dt.astimezone(timezone.utc).isoformat(),
            "display": dt.strftime("%d %b %Y, %I:%M:%S %p IST"),
            "source": line,
        }

    return fallback


def load_latest_gate_status(log_path: Path | None = None) -> dict[str, object]:
    active_log_path = log_path or RUNTIME_LOG_PATH
    entry_required = APP_CONFIG.trading.entry_confirmations_required
    exit_required = APP_CONFIG.trading.exit_confirmations_required
    fallback = {
        "action": "wait",
        "no_trade": True,
        "active_state": "",
        "display_active_state": "No Active Trade",
        "candidate_state": "",
        "display_candidate_state": "Waiting",
        "candidate_count": 0,
        "opposite_count": 0,
        "reason": "awaiting_runtime_gate_updates",
        "display_reason": "Awaiting Runtime Gate Updates",
        "entry_confirmations_required": entry_required,
        "exit_confirmations_required": exit_required,
        "summary": f"Entries need {entry_required} consecutive 1-minute matches; exits need {exit_required} consecutive non-matching 1-minute checks.",
    }
    if not active_log_path.exists():
        return fallback

    pattern = re.compile(
        r"PAPER_EVAL_GATE \| state=(.*?) no_trade=(.*?) action=(.*?) active_state=(.*?) candidate=(.*?) candidate_count=(\d+) opposite_count=(\d+) reason=(.*)$"
    )

    try:
        with active_log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(size - 256_000, 0))
            lines = fh.read().decode("utf-8", errors="ignore").splitlines()
    except Exception:
        return fallback

    parsed: dict[str, object] | None = None
    for line in reversed(lines[-4000:]):
        match = pattern.search(line)
        if match is None:
            continue
        state_name, no_trade, action, active_state, candidate_state, candidate_count, opposite_count, reason = match.groups()
        parsed = {
            "state_name": state_name.strip(),
            "no_trade": str(no_trade).strip().lower() == "true",
            "action": str(action).strip(),
            "active_state": str(active_state).strip(),
            "candidate_state": str(candidate_state).strip(),
            "candidate_count": int(candidate_count),
            "opposite_count": int(opposite_count),
            "reason": str(reason).strip(),
            "entry_confirmations_required": entry_required,
            "exit_confirmations_required": exit_required,
        }
        break

    if parsed is None:
        return fallback

    action = str(parsed.get("action", "") or "wait")
    active_state = str(parsed.get("active_state", "") or "")
    candidate_state = str(parsed.get("candidate_state", "") or "")
    reason = str(parsed.get("reason", "") or "")
    candidate_count = int(parsed.get("candidate_count", 0) or 0)
    opposite_count = int(parsed.get("opposite_count", 0) or 0)

    display_candidate = "No Trade" if candidate_state == "NO_TRADE" else nice_label(candidate_state, default="Waiting")
    display_active = "No Active Trade" if not active_state else nice_label(active_state)
    summary = fallback["summary"]

    if action == "wait":
        if candidate_state and candidate_state != "NO_TRADE":
            summary = f"Entry confirmation pending for {display_candidate}: {candidate_count}/{entry_required} matching 1-minute checks."
        else:
            summary = f"Entry waits for {entry_required} consecutive 1-minute tradeable-state checks."
    elif action == "enter":
        summary = f"Entry confirmed for {display_candidate} after {entry_required} consecutive 1-minute checks."
    elif action == "hold":
        if active_state and opposite_count > 0:
            summary = f"Exit confirmation pending for {display_active}: {opposite_count}/{exit_required} non-matching 1-minute checks."
        elif active_state:
            summary = f"Active trade still matches {display_active}. Exit needs {exit_required} consecutive non-matching 1-minute checks."
        else:
            summary = f"Waiting for {entry_required} consecutive 1-minute checks before the next entry."
    elif action == "switch":
        summary = f"State switch confirmed to {display_candidate} after {entry_required} consecutive 1-minute checks."
    elif action == "exit":
        summary = f"Exit confirmed after {exit_required} consecutive non-matching 1-minute checks."
        if reason.startswith("confirmed_exit_from:"):
            previous_state = reason.split(":", 1)[1]
            summary = f"Exit confirmed from {nice_label(previous_state)} after {exit_required} consecutive non-matching 1-minute checks."

    return {
        **parsed,
        "display_active_state": display_active,
        "display_candidate_state": display_candidate,
        "display_reason": nice_label(reason, default="Waiting"),
        "summary": summary,
    }


def extract_session_date(value: object) -> str:
    text = str(value or "").strip()
    if len(text) >= 10:
        return text[:10]
    return ""


def extract_session_date_from_item(item: dict[str, object]) -> str:
    session_date = extract_session_date(item.get("session_date", ""))
    if session_date:
        return session_date
    return extract_session_date(item.get("closed_at", ""))


def is_current_session_item(item: dict[str, object], *, session_date: str) -> bool:
    if not session_date:
        return True
    item_session_date = extract_session_date_from_item(item)
    return bool(item_session_date) and item_session_date == session_date


def classify_closed_item(item: dict[str, object]) -> dict[str, str]:
    realised_pnl = abs(safe_float(item.get("realised_pnl", 0.0)))
    mtm_points = abs(safe_float(item.get("mtm_points", 0.0)))
    entry_credit = abs(safe_float(item.get("entry_credit", 0.0)))
    entry_debit = abs(safe_float(item.get("entry_debit", 0.0)))
    close_value = abs(safe_float(item.get("current_close_value", 0.0)))
    was_live = bool(item.get("was_live", False))

    if was_live or any(value > 0 for value in (realised_pnl, mtm_points, entry_credit, entry_debit, close_value)):
        return {
            "activity_type": "paper_trade",
            "display_activity_type": "Paper trade",
            "activity_note": "Live MTM or booked trade values were available for this closure.",
        }

    return {
        "activity_type": "signal_only",
        "display_activity_type": "Signal-only closure",
        "activity_note": "This closure came from the signal engine without live marked trade values.",
    }


def load_state_history(log_path: Path | None = None, *, session_date: str = "") -> dict[str, object]:
    active_log_path = log_path or RUNTIME_LOG_PATH
    fallback = {
        "entry_count": 0,
        "tradeable_count": 0,
        "current_state": "Waiting",
        "first_seen": "-",
        "last_seen": "-",
        "summary": "No state history captured yet for this session.",
        "counts": {},
        "entries": [],
    }
    if not active_log_path.exists():
        return fallback

    pattern = re.compile(
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) \| state_engine \| INFO \| STATE \| state=(.*?) confidence=(.*?) tradeable=(.*?) ambiguity=(.*?) evidence=(.*)$"
    )
    phase_pattern = re.compile(r"'session_phase': '([^']+)'")

    try:
        with active_log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(size - 1_000_000, 0))
            lines = fh.read().decode("utf-8", errors="ignore").splitlines()
    except Exception:
        return fallback

    market_tz = MarketCalendar().timezone
    entries: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    tradeable_count = 0

    for line in lines:
        match = pattern.match(line)
        if match is None:
            continue
        stamp_text, state_name, confidence, tradeable_raw, ambiguity, evidence = match.groups()
        if session_date and not stamp_text.startswith(session_date):
            continue
        try:
            stamp = datetime.strptime(stamp_text, "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=market_tz)
        except ValueError:
            continue
        tradeable = str(tradeable_raw).strip().lower() == "true"
        if tradeable:
            tradeable_count += 1
        counts[state_name] = counts.get(state_name, 0) + 1
        phase_match = phase_pattern.search(evidence)
        entries.append(
            {
                "timestamp": stamp.isoformat(),
                "display_time": stamp.strftime("%I:%M %p IST"),
                "state": state_name,
                "display_state": nice_label(state_name),
                "confidence": confidence,
                "tradeable": tradeable,
                "display_tradeable": "Yes" if tradeable else "No",
                "ambiguity": ambiguity if ambiguity and ambiguity != "none" else "-",
                "session_phase": phase_match.group(1) if phase_match else "",
            }
        )

    if not entries:
        return fallback

    counts_summary = ", ".join(
        f"{name}: {count}" for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:4]
    )
    return {
        "entry_count": len(entries),
        "tradeable_count": tradeable_count,
        "current_state": entries[-1]["display_state"],
        "first_seen": str(entries[0]["display_time"]),
        "last_seen": str(entries[-1]["display_time"]),
        "summary": counts_summary or "No state history captured yet for this session.",
        "counts": counts,
        "entries": entries[-60:],
    }


def load_latest_decision_context(log_path: Path | None = None) -> dict[str, object]:
    active_log_path = log_path or RUNTIME_LOG_PATH
    fallback = {
        "state": "Waiting",
        "display_state": "Waiting",
        "confidence": "-",
        "tradeable": False,
        "display_tradeable": "No",
        "ambiguity": "",
        "display_ambiguity": "-",
        "edge_reason": "",
        "display_edge_reason": "Awaiting Decision Update",
        "playbook": "",
        "display_playbook": "No Trade",
        "no_trade": True,
        "decision_status": "No trade",
        "summary": "Waiting for the runtime to evaluate the latest 1-minute candle.",
        "criteria_checks": [],
    }
    if not active_log_path.exists():
        return fallback

    state_pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \| state_engine \| INFO \| STATE \| state=(.*?) confidence=(.*?) tradeable=(.*?) ambiguity=(.*?) evidence=(.*)$"
    )
    edge_pattern = re.compile(r"EDGE \| playbook=(.*?) no_trade=(.*?) reason=(.*?) alternatives=(.*)$")
    playbook_pattern = re.compile(r"PLAYBOOK \| selected=(.*?) no_trade=(.*?) reason=(.*?) alternatives=(.*)$")

    try:
        with active_log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(size - 256_000, 0))
            lines = fh.read().decode("utf-8", errors="ignore").splitlines()
    except Exception:
        return fallback

    state_match = None
    edge_match = None
    playbook_match = None
    for line in reversed(lines):
        if state_match is None:
            state_match = state_pattern.search(line)
            if state_match is not None:
                continue
        if edge_match is None:
            edge_match = edge_pattern.search(line)
            if edge_match is not None:
                continue
        if playbook_match is None:
            playbook_match = playbook_pattern.search(line)
            if playbook_match is not None:
                continue
        if state_match is not None and edge_match is not None and playbook_match is not None:
            break

    if state_match is None:
        return fallback

    state_name, confidence, tradeable_raw, ambiguity, evidence_text = state_match.groups()
    tradeable = str(tradeable_raw).strip().lower() == "true"
    evidence: dict[str, object] = {}
    try:
        parsed_evidence = ast.literal_eval(evidence_text)
        if isinstance(parsed_evidence, dict):
            evidence = parsed_evidence
    except Exception:
        evidence = {}

    edge_reason = edge_match.group(3).strip() if edge_match is not None else ""
    no_trade = str(edge_match.group(2)).strip().lower() == "true" if edge_match is not None else (not tradeable)
    selected_playbook = playbook_match.group(1).strip() if playbook_match is not None else ("no_trade" if no_trade else "")

    gap_pct = safe_float(evidence.get("gap_pct", 0.0))
    range_pct = safe_float(evidence.get("realized_range_pct", 0.0))
    distance_to_mid_pct = safe_float(evidence.get("distance_to_mid_pct", 0.0))
    close_location = safe_float(evidence.get("close_location", 0.0))
    current_price = safe_float(evidence.get("current_price", 0.0))
    prior_close = safe_float(evidence.get("prior_close", 0.0))
    session_open = safe_float(evidence.get("session_open", 0.0))
    session_extension_pct = abs(current_price - session_open) / max(abs(prior_close), 1.0)

    criteria_checks = [
        {
            "label": "Gap filter",
            "passed": abs(gap_pct) >= 0.003,
            "detail": f"{gap_pct * 100:.2f}% vs ±0.30% threshold",
        },
        {
            "label": "Controlled range",
            "passed": range_pct <= 0.0035 and distance_to_mid_pct <= 0.0015,
            "detail": f"range {range_pct * 100:.2f}% and mid-distance {distance_to_mid_pct * 100:.2f}%",
        },
        {
            "label": "Trend conviction",
            "passed": (close_location >= 0.75 or close_location <= 0.25) and session_extension_pct >= 0.0025,
            "detail": f"close location {close_location:.2f}, extension {session_extension_pct * 100:.2f}%",
        },
        {
            "label": "Volatility expansion",
            "passed": range_pct >= 0.009,
            "detail": f"range {range_pct * 100:.2f}% vs 0.90% trigger",
        },
    ]

    display_state = nice_label(state_name)
    display_playbook = display_label(selected_playbook, default="No Trade")
    display_edge_reason = nice_label(edge_reason, default="Awaiting Decision Update")
    display_ambiguity = nice_label(ambiguity, default="-") if ambiguity and ambiguity != "none" else "-"

    if no_trade:
        summary = f"No new trade because the latest state is {display_state} and the edge filter returned {display_edge_reason}."
    else:
        summary = f"Trade criteria are currently satisfied: {display_state} → {display_playbook}."

    return {
        "state": state_name,
        "display_state": display_state,
        "confidence": confidence,
        "tradeable": tradeable,
        "display_tradeable": "Yes" if tradeable else "No",
        "ambiguity": ambiguity,
        "display_ambiguity": display_ambiguity,
        "edge_reason": edge_reason,
        "display_edge_reason": display_edge_reason,
        "playbook": selected_playbook,
        "display_playbook": display_playbook,
        "no_trade": no_trade,
        "decision_status": "No trade" if no_trade else "Eligible",
        "summary": summary,
        "criteria_checks": criteria_checks,
    }


def resolve_expiry_label(expiry: str, session_date: str = "") -> str:
    if not expiry:
        return "-"

    calendar = MarketCalendar()
    try:
        anchor = datetime.strptime(session_date, "%Y-%m-%d").date() if session_date else calendar.today()
    except ValueError:
        anchor = calendar.today()

    if expiry == "same_day":
        return anchor.strftime("%d %b %Y")
    if expiry == "same_week":
        return calendar.next_expiry(anchor).strftime("%d %b %Y")
    if expiry == "next_week":
        next_expiry = calendar.next_expiry(anchor)
        return calendar.next_expiry(next_expiry + timedelta(days=7)).strftime("%d %b %Y")

    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(expiry, fmt).strftime("%d %b %Y")
        except ValueError:
            continue
    return nice_label(expiry)


def describe_current_view(state: str, playbook: str, is_active: bool, runtime_status: str = "LIVE") -> str:
    if not is_active:
        if runtime_status == "STOPPED":
            return "The trading session is closed, so the system is currently stopped and waiting for the next valid market window."
        if runtime_status == "STALE":
            return "The dashboard has not updated recently, so the live view may be stale until the runtime resumes normal updates."
        return "The system is live and watching the market, but no fresh setup is active right now."

    descriptions = {
        "Expiry Compression": "The market looks relatively calm near expiry, so the engine is favouring a contained range-style setup.",
        "Trend Continuation": "The market looks directional, and the engine is leaning toward a trend-following setup.",
        "Gap Continuation": "The market appears to be accepting the opening move, so the engine is favouring continuation rather than fading it.",
        "Controlled Range": "The market is behaving like a range, so the engine is favouring defined-risk premium-selling structures.",
        "Volatility Expansion": "The market is moving more aggressively, so the engine is leaning toward a movement-focused structure.",
        "Expiry Gamma Expansion": "Expiry behaviour is sharp and fast, so the engine is favouring a quick tactical setup.",
    }
    summary = descriptions.get(state, "The engine is actively evaluating the latest completed candle.")
    if playbook:
        return f"{summary} Current idea: {display_label(playbook)}."
    return summary


def prepare_record(row: dict[str, str]) -> dict[str, object]:
    context = safe_json_loads(row.get("underlying_context", ""), {})
    strikes = safe_json_loads(row.get("strike_or_strikes", ""), [])
    entry_prices = safe_json_loads(row.get("entry_price_or_prices", ""), [])
    legs = safe_json_loads(row.get("legs_json", ""), [])
    option_types = safe_json_loads(row.get("option_types", ""), [])
    quantity_raw = row.get("quantity", "0")
    try:
        lots = int(float(quantity_raw or 0))
    except ValueError:
        lots = 0

    underlying_price = context.get("underlying_price")
    if isinstance(underlying_price, (int, float)):
        underlying_price = round(float(underlying_price), 2)

    strike_labels = [str(int(strike)) if float(strike).is_integer() else str(strike) for strike in strikes] if strikes else []
    if not option_types and isinstance(legs, list):
        option_types = sorted({str(leg.get("option_type", "") or "").upper() for leg in legs if isinstance(leg, dict) and leg.get("option_type")})
    option_types = [str(option_type).upper() for option_type in option_types if str(option_type).strip()]
    display_option_types = "/".join(option_types) if option_types else "-"

    playbook_name = str(row.get("playbook", ""))
    structure_type = str(row.get("structure_type", ""))
    display_playbook = display_label(playbook_name)
    if playbook_name in {"call_or_put_credit_spread", "defined_risk_credit_spread"}:
        if option_types == ["PE"]:
            display_playbook = "Put Credit Spread"
        elif option_types == ["CE"]:
            display_playbook = "Call Credit Spread"

    display_strikes = ", ".join(strike_labels) if strike_labels else "-"
    display_legs = display_strikes
    if isinstance(legs, list) and legs:
        leg_labels = []
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            strike = leg.get("strike")
            try:
                strike_text = str(int(float(strike))) if float(strike).is_integer() else str(strike)
            except (TypeError, ValueError):
                strike_text = str(strike or "-")
            option_type = str(leg.get("option_type", "") or "").upper()
            side = str(leg.get("side", "") or "").title()
            label_bits = [bit for bit in (strike_text, option_type, side) if bit and bit != "-"]
            if label_bits:
                leg_labels.append(" ".join(label_bits))
        if leg_labels:
            display_legs = ", ".join(leg_labels)
    elif strike_labels and display_option_types != "-":
        if structure_type in {"call_or_put_credit_spread", "defined_risk_credit_spread"} and len(strike_labels) == 2:
            display_legs = f"{strike_labels[0]} {display_option_types} BUY, {strike_labels[1]} {display_option_types} SELL"
        elif structure_type in {"bull_call_spread_or_bear_put_spread", "reversal_debit_spread", "expiry_directional_scalp"} and len(strike_labels) == 2:
            display_legs = f"{strike_labels[0]} {display_option_types} BUY, {strike_labels[1]} {display_option_types} SELL"
        else:
            display_legs = ", ".join(f"{strike} {display_option_types}" for strike in strike_labels)

    session_date = str(row.get("session_date", ""))
    return {
        **row,
        "display_trade_id": clean_trade_id(str(row.get("trade_id", ""))),
        "display_state": nice_label(row.get("state_at_entry", "")),
        "display_playbook": display_playbook,
        "display_structure": display_label(str(row.get("structure_type", ""))),
        "display_reason": display_reason(str(row.get("exit_reason", ""))),
        "display_expiry": resolve_expiry_label(str(row.get("expiry", "")), session_date),
        "underlying_price": underlying_price,
        "paper_mode": bool(context.get("paper_mode", False)),
        "strikes": strikes,
        "display_strikes": display_strikes,
        "display_legs": display_legs,
        "display_option_types": display_option_types,
        "entry_prices": entry_prices,
        "lots": lots,
        "quantity": lots,
    }


def build_dashboard_payload(data_dir: Path = DEFAULT_DATA_DIR) -> dict:
    reports_dir = data_dir / "reports"
    records_dir = data_dir / "records"
    summary_file = latest_matching_file(reports_dir, "trade_summary_*.json")
    records_file = latest_matching_file(records_dir, "trade_records_*.csv")
    live_mtm_file = reports_dir / "live_paper_mtm.json"

    summary = load_json(summary_file, {}) if summary_file else {}
    live_mtm = load_json(live_mtm_file, {}) if live_mtm_file.exists() else {}
    recent_rows = load_csv_rows(records_file) if records_file else []
    recent_rows = list(reversed(recent_rows[-20:]))
    recent_records = [prepare_record(row) for row in recent_rows]

    last_update_ts = None
    for path in [summary_file, records_file, live_mtm_file]:
        if path and path.exists():
            last_update_ts = max(last_update_ts or 0.0, path.stat().st_mtime)

    now_ts = datetime.now(timezone.utc).timestamp()
    data_is_fresh = bool(last_update_ts and (now_ts - last_update_ts) <= FRESHNESS_SEC)
    runtime_heartbeat = load_runtime_heartbeat()
    runtime_heartbeat_ts = runtime_heartbeat.get("timestamp")
    runtime_is_fresh = bool(runtime_heartbeat_ts and (now_ts - float(runtime_heartbeat_ts)) <= FRESHNESS_SEC)
    is_fresh = bool(data_is_fresh or runtime_is_fresh)
    effective_update_ts = max(ts for ts in (last_update_ts, runtime_heartbeat_ts) if ts is not None) if any(ts is not None for ts in (last_update_ts, runtime_heartbeat_ts)) else None
    last_update_iso = (
        datetime.fromtimestamp(effective_update_ts, tz=timezone.utc).astimezone().isoformat()
        if effective_update_ts
        else ""
    )

    latest_signal = recent_records[0] if recent_records else {}
    latest_state = str(latest_signal.get("state_at_entry", ""))
    latest_playbook = str(latest_signal.get("playbook", ""))
    has_recent_signal = bool(is_fresh and latest_signal)
    live_mtm_enabled = bool(live_mtm.get("live", False)) and is_fresh
    live_mtm_mode = str(live_mtm.get("mode", "") or "")
    live_trade_id = str(live_mtm.get("trade_id", "") or "")
    pending_trade_active = bool(
        is_fresh
        and live_trade_id
        and not live_mtm_enabled
        and live_mtm_mode not in {"", "waiting_for_trade", "signal_only"}
    )
    trade_happening_now = bool(live_mtm_enabled or pending_trade_active)
    recent_closed = live_mtm.get("recent_closed", []) if isinstance(live_mtm.get("recent_closed", []), list) else []

    calendar = MarketCalendar()
    display_session_date = str(
        summary.get("session_date", "")
        or latest_signal.get("session_date", "")
        or live_mtm.get("session_date", "")
        or calendar.today().isoformat()
    )
    gate_status = load_latest_gate_status()
    state_history = load_state_history(session_date=display_session_date)
    decision_context = load_latest_decision_context()
    current_market_state = str(decision_context.get("display_state", "") or state_history.get("current_state", "") or nice_label(latest_state))

    summary_session_date = extract_session_date(summary.get("session_date", ""))
    summary_is_session_scoped = bool(summary_session_date and summary_session_date == display_session_date)
    summary_net_pnl = round(safe_float(summary.get("net_pnl", 0.0)), 2) if summary_is_session_scoped else 0.0

    session_closed = [item for item in recent_closed if isinstance(item, dict) and is_current_session_item(item, session_date=display_session_date)]
    last_closed = session_closed[0] if session_closed else {}

    classified_session_closed = [
        {
            "trade_id": str(item.get("trade_id", "")),
            "display_trade_id": clean_trade_id(str(item.get("trade_id", ""))),
            "playbook": str(item.get("playbook", "")),
            "display_playbook": display_label(str(item.get("playbook") or item.get("structure_type", ""))),
            "structure_type": str(item.get("structure_type", "")),
            "display_structure": display_label(str(item.get("structure_type", ""))),
            "exit_reason": str(item.get("exit_reason", "")),
            "display_reason": display_reason(str(item.get("exit_reason", ""))),
            "closed_at": str(item.get("closed_at", "")),
            "display_closed_at": format_display_timestamp(item.get("closed_at", "")),
            "realised_pnl": safe_float(item.get("realised_pnl", 0.0)),
            "mtm_points": safe_float(item.get("mtm_points", 0.0)),
            **classify_closed_item(item),
        }
        for item in session_closed
    ]
    booked_trade_count = sum(1 for item in classified_session_closed if item.get("activity_type") == "paper_trade")
    signal_only_count = sum(1 for item in classified_session_closed if item.get("activity_type") == "signal_only")
    closed_trades = [item for item in classified_session_closed if item.get("activity_type") == "paper_trade"][:5]
    signal_only_closed_trades = [item for item in classified_session_closed if item.get("activity_type") == "signal_only"][:5]

    raw_mtm_session_date = extract_session_date(live_mtm.get("session_date", ""))
    recent_closed_sessions = {extract_session_date_from_item(item) for item in recent_closed if isinstance(item, dict) and extract_session_date_from_item(item)}
    live_mtm_totals_are_session_scoped = bool(
        live_mtm_enabled
        or (raw_mtm_session_date and raw_mtm_session_date == display_session_date)
        or (recent_closed_sessions and recent_closed_sessions == {display_session_date})
    )
    live_mtm_realised_pnl = round(safe_float(live_mtm.get("realised_pnl_today", 0.0)), 2)
    live_mtm_closed_count = int(live_mtm.get("closed_trade_count", 0) or 0)
    live_mtm_totals_match_summary = (not summary_is_session_scoped) or abs(live_mtm_realised_pnl - summary_net_pnl) <= 0.01
    trust_live_mtm_totals = bool(
        live_mtm_totals_are_session_scoped
        and (
            (summary_is_session_scoped and live_mtm_totals_match_summary)
            or (not summary_is_session_scoped and (live_mtm_enabled or booked_trade_count > 0))
        )
    )

    session_realised_pnl = summary_net_pnl if summary_is_session_scoped else round(
        sum(safe_float(item.get("realised_pnl", 0.0)) for item in session_closed),
        2,
    )
    session_closed_count = len(session_closed)
    if trust_live_mtm_totals:
        session_realised_pnl = live_mtm_realised_pnl
        session_closed_count = live_mtm_closed_count or session_closed_count

    market_phase = calendar.classify_timestamp()
    runtime_status = "LIVE" if is_fresh else ("STALE" if market_phase == "open" else "STOPPED")

    if live_mtm_enabled:
        strip_status = "OPEN"
    elif pending_trade_active:
        strip_status = "ENTERED"
    elif runtime_status == "STALE":
        strip_status = "STALE"
    elif runtime_status == "STOPPED":
        strip_status = "STOPPED"
    else:
        strip_status = "WATCHING"

    if live_mtm_enabled:
        status_text = "Trade live"
    elif pending_trade_active:
        status_text = "Trade entered"
    elif is_fresh:
        status_text = "Watching for setup"
    elif runtime_status == "STALE":
        status_text = "System stale"
    else:
        status_text = "System stopped"

    pnl_reason = str(
        live_mtm.get(
            "reason",
            "Current rebuild logs signals and live marks using the active execution mode.",
        )
    )
    if live_mtm_totals_are_session_scoped and not trust_live_mtm_totals:
        pnl_reason = (
            f"Showing only the displayed session ({display_session_date}). Older carried-over booked values from the MTM file "
            "are hidden because they do not match today's session summary."
        )
    elif pending_trade_active:
        pnl_reason = "A trade has been entered and is waiting for option prices. Live P&L will appear when the option legs start ticking."
    elif not live_mtm_enabled and not live_mtm_totals_are_session_scoped:
        pnl_reason = f"Showing only the displayed session ({display_session_date}). Older carried-over booked values are hidden."
    elif not live_mtm_enabled and session_closed_count > 0 and session_realised_pnl == 0.0:
        pnl_reason = "Recent session closures were signal-only or not live-marked, so booked P&L is still zero."

    alerts: list[str] = []
    if runtime_status == "STALE":
        alerts.append(
            f"Dashboard updates are stale. Last runtime update: {format_display_timestamp(last_update_iso) if last_update_iso else '-'}"
        )
    if pending_trade_active:
        alerts.append("A trade has been entered and is waiting for option prices before live P&L can be shown.")
    elif not trade_happening_now:
        alerts.append("No live trade is open right now. The engine is waiting for the next valid setup.")
    if signal_only_count > 0:
        alerts.append(f"{signal_only_count} signal-only closures are hidden from booked P&L totals.")
    if session_realised_pnl == 0.0 and int(summary.get("total_trades", 0) or 0) > 0:
        alerts.append("Trades were evaluated today, but no booked paper-trade P&L has been confirmed yet.")

    session_unrealised_pnl = round(safe_float(live_mtm.get("unrealised_pnl", 0.0)), 2) if live_mtm_enabled else 0.0
    session_total_pnl = round(session_realised_pnl + session_unrealised_pnl, 2)
    open_positions = []
    active_records: list[dict[str, object]] = []
    if trade_happening_now and live_trade_id:
        active_records = [record for record in recent_records if str(record.get("trade_id", "") or "") == live_trade_id]
    elif trade_happening_now and latest_signal:
        active_records = [latest_signal]

    for record in active_records[:1]:
        trade_id = str(record.get("trade_id", "") or "")
        display_trade_id = str(record.get("display_trade_id", "") or clean_trade_id(trade_id))
        is_live_trade = bool(trade_id and trade_id == live_trade_id)
        status_label = "Live" if (is_live_trade and live_mtm_enabled) else ("Entered" if is_live_trade or pending_trade_active else "Open")
        entry_prices = record.get("entry_prices", []) if isinstance(record.get("entry_prices", []), list) else []
        open_positions.append(
            {
                "trade_id": trade_id,
                "display_trade_id": display_trade_id,
                "display_playbook": str(record.get("display_playbook", "") or "Waiting"),
                "display_state": str(record.get("display_state", "") or "Waiting"),
                "display_structure": str(record.get("display_structure", "") or "Waiting"),
                "display_status": status_label,
                "display_entry_time": format_display_timestamp(record.get("opened_at", "")),
                "display_strikes": str(record.get("display_legs", record.get("display_strikes", "-")) or "-"),
                "display_option_types": str(record.get("display_option_types", "-") or "-"),
                "quantity": int(record.get("quantity", 0) or 0),
                "entry_value": safe_float(entry_prices[0], 0.0) if entry_prices else 0.0,
                "underlying_price": record.get("underlying_price"),
                "unrealised_pnl": session_unrealised_pnl if is_live_trade else 0.0,
                "live_available": bool(is_live_trade and live_mtm_enabled),
            }
        )

    pnl_history = [
        {
            "time": format_display_timestamp(live_mtm.get("last_update", "") or last_update_iso),
            "realised": session_realised_pnl,
            "unrealised": session_unrealised_pnl,
            "total": session_total_pnl,
        }
    ]

    return {
        "status": {
            "mode": APP_CONFIG.trading.execution_mode.value,
            "live_trading_enabled": APP_CONFIG.trading.live_trading_enabled,
            "runtime_running": is_fresh,
            "paper_eval_running": is_fresh,
            "runtime_status": runtime_status,
            "last_update": last_update_iso,
            "last_update_display": format_display_timestamp(last_update_iso),
            "data_last_update": datetime.fromtimestamp(last_update_ts, tz=timezone.utc).astimezone().isoformat() if last_update_ts else "",
            "data_last_update_display": format_display_timestamp(datetime.fromtimestamp(last_update_ts, tz=timezone.utc).astimezone().isoformat()) if last_update_ts else "-",
            "runtime_last_seen": str(runtime_heartbeat.get("iso", "")),
            "runtime_last_seen_display": str(runtime_heartbeat.get("display", "-")),
            "clock_display": datetime.now(calendar.timezone).strftime("%H:%M:%S"),
        },
        "session_date": display_session_date,
        "summary": {
            "total_trades": int(summary.get("total_trades", 0) or 0),
            "gross_pnl": float(summary.get("gross_pnl", 0.0) or 0.0),
            "fees_and_costs": float(summary.get("fees_and_costs", 0.0) or 0.0),
            "net_pnl": float(summary.get("net_pnl", 0.0) or 0.0),
            "by_state": summary.get("by_state", {}),
            "by_playbook": summary.get("by_playbook", {}),
        },
        "latest_signal": {
            "trade_id": latest_signal.get("trade_id", ""),
            "display_trade_id": latest_signal.get("display_trade_id", clean_trade_id(str(latest_signal.get("trade_id", "")))),
            "state": nice_label(latest_state),
            "playbook": latest_playbook,
            "display_playbook": latest_signal.get("display_playbook", display_label(latest_playbook)),
            "structure": latest_signal.get("structure_type", ""),
            "display_structure": latest_signal.get("display_structure", display_label(str(latest_signal.get("structure_type", "")))),
            "expiry": latest_signal.get("expiry", ""),
            "display_expiry": latest_signal.get("display_expiry", resolve_expiry_label(str(latest_signal.get("expiry", "")), str(summary.get("session_date", "")))),
            "underlying_price": latest_signal.get("underlying_price"),
            "strikes": latest_signal.get("strikes", []),
            "display_strikes": latest_signal.get("display_strikes", "-"),
            "exit_reason": latest_signal.get("exit_reason", ""),
            "display_reason": latest_signal.get("display_reason", display_reason(str(latest_signal.get("exit_reason", "")))),
            "side": latest_signal.get("side", ""),
            "lots": int(latest_signal.get("quantity", 0) or 0) if latest_signal else 0,
        },
        "headline": {
            "status_text": status_text,
            "current_state": current_market_state,
            "current_playbook": latest_playbook,
            "display_current_playbook": latest_signal.get("display_playbook", display_label(latest_playbook)),
            "current_structure": latest_signal.get("structure_type", ""),
            "display_current_structure": latest_signal.get("display_structure", display_label(str(latest_signal.get("structure_type", "")))),
            "plain_english": describe_current_view(current_market_state, latest_playbook, trade_happening_now, runtime_status),
            "trade_underway": trade_happening_now,
            "recent_signal_seen": has_recent_signal,
        },
        "trade_strip": {
            "status": strip_status,
            "status_note": (
                "A paper trade is open and live P&L is updating."
                if strip_status == "OPEN"
                else (
                    "A trade has been entered and is waiting for option prices to show progress."
                    if strip_status == "ENTERED"
                    else (
                        "Live updates are stale, so session closure info below may lag."
                        if strip_status == "STALE"
                        else (
                            "The session is currently stopped outside market hours."
                            if strip_status == "STOPPED"
                            else str(gate_status.get("summary", "System is watching for the next setup"))
                        )
                    )
                )
            ),
            "last_exit_reason": display_reason(str(last_closed.get("exit_reason", "")), default="No current-session closure yet"),
            "last_closed_trade_id": str(last_closed.get("trade_id", "")),
            "display_last_closed_trade_id": clean_trade_id(str(last_closed.get("trade_id", ""))),
            "closed_trade_count": session_closed_count,
            "display_scope": f"{display_session_date} session only",
        },
        "pnl_status": {
            "live": live_mtm_enabled,
            "mode": str(live_mtm.get("mode", "live_mtm" if live_mtm_enabled else "signal_only")),
            "reason": pnl_reason,
            "display_scope": f"{display_session_date} session only",
            "trade_id": str(live_mtm.get("trade_id", "")),
            "display_trade_id": clean_trade_id(str(live_mtm.get("trade_id", ""))),
            "entry_credit": safe_float(live_mtm.get("entry_credit", 0.0)),
            "entry_debit": safe_float(live_mtm.get("entry_debit", 0.0)),
            "current_close_value": safe_float(live_mtm.get("current_close_value", 0.0)),
            "underlying_price": safe_float(live_mtm.get("underlying_price", 0.0)),
            "mtm_points": safe_float(live_mtm.get("mtm_points", 0.0)),
            "unrealised_pnl": safe_float(live_mtm.get("unrealised_pnl", 0.0)),
            "realised_pnl_today": session_realised_pnl,
            "closed_trade_count": session_closed_count,
            "booked_trade_count": booked_trade_count,
            "signal_only_count": signal_only_count,
            "last_update": str(live_mtm.get("last_update", "")),
            "last_update_display": format_display_timestamp(live_mtm.get("last_update", "")),
        },
        "portfolio": {
            "total_pnl": session_total_pnl,
            "realised_pnl": session_realised_pnl,
            "unrealised_pnl": session_unrealised_pnl,
            "open_positions": len(open_positions),
            "booked_trade_count": booked_trade_count,
            "signal_only_count": signal_only_count,
        },
        "simple_status": {
            "entries_taken_today": int(summary.get("total_trades", 0) or 0),
            "trade_happening_now": "Yes" if trade_happening_now else "No",
            "trade_status": (
                "Live P&L running"
                if live_mtm_enabled
                else ("Entered, waiting for prices" if pending_trade_active else ("Watching for setup" if runtime_status == "LIVE" else runtime_status.title()))
            ),
            "progress_summary": (
                "Trade is open and live P&L is updating."
                if live_mtm_enabled
                else (
                    "Trade has been entered and is waiting for option prices to show live progress."
                    if pending_trade_active
                    else str(decision_context.get("summary", "Waiting for the next setup."))
                )
            ),
            "current_trade_id": live_trade_id,
            "display_current_trade_id": clean_trade_id(live_trade_id),
            "current_trade_playbook": display_label(str(live_mtm.get("playbook", "") or latest_playbook), default="Waiting"),
            "last_closed_trade_id": str(last_closed.get("trade_id", "")),
            "display_last_closed_trade_id": clean_trade_id(str(last_closed.get("trade_id", ""))),
            "last_closed_reason": display_reason(str(last_closed.get("exit_reason", "")), default="No closed trade yet"),
            "last_closed_pnl": safe_float(last_closed.get("realised_pnl", 0.0)),
        },
        "alerts": alerts,
        "ops": {
            "control_mode": "terminal_or_systemd",
            "public_controls_enabled": False,
            "runtime_start": "python3 scripts/run_paper_live_eval.py",
            "runtime_stop": "pkill -f 'scripts/run_paper_live_eval.py'",
            "paper_eval_start": "python3 scripts/run_paper_live_eval.py",
            "paper_eval_stop": "pkill -f 'scripts/run_paper_live_eval.py'",
            "monitor_start": "./run_monitoring.sh",
            "monitor_stop": "pkill -f 'monitoring_web.py'",
        },
        "confirmation_gate": gate_status,
        "state_history": state_history,
        "decision_context": decision_context,
        "recent_records": recent_records,
        "open_positions": open_positions,
        "pnl_history": pnl_history,
        "closed_trades": closed_trades,
        "signal_only_closed_trades": signal_only_closed_trades,
    }


def render_index() -> str:
    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>NIFTY Trading Monitor</title>
  <link rel=\"icon\" href=\"/favicon.ico\" />
  <link rel=\"shortcut icon\" href=\"/favicon.ico\" />
  <style>
    :root {
      --page-bg: #e8e8e8;
      --card-bg: #f8f8f8;
      --card-border: #cfcfcf;
      --header-dark: #1b2129;
      --header-blue: #156ff6;
      --text: #1e2329;
      --muted: #66707a;
      --line: #dcdcdc;
      --green: #23804e;
      --red: #d63f3f;
      --amber: #b87912;
      --shadow: 0 1px 0 rgba(0, 0, 0, 0.05);
      --radius: 18px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--page-bg);
      color: var(--text);
      font-family: "Segoe UI", Arial, sans-serif;
    }
    .page {
      max-width: 1180px;
      margin: 18px auto 40px;
      padding: 0 14px;
    }
    .block {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      overflow: hidden;
      box-shadow: var(--shadow);
      margin-bottom: 18px;
    }
    .block-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 18px 28px;
      color: #fff;
    }
    .block-header.dark { background: linear-gradient(90deg, #171d24, #202833); }
    .block-header.blue { background: #156ff6; }
    .block-header h2 {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2rem, 4vw, 2.25rem);
      font-weight: 800;
    }
    .header-sub {
      font-size: 0.82rem;
      opacity: 0.88;
      margin-bottom: 4px;
      letter-spacing: 0.04em;
    }
    .header-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 120px;
      padding: 10px 18px;
      border-radius: 12px;
      border: 2px solid rgba(255,255,255,0.85);
      color: #fff;
      text-decoration: none;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.05rem;
      background: rgba(255,255,255,0.05);
    }
    .block-body { padding: 22px 28px; }
    .status-grid, .portfolio-grid, .diag-grid {
      display: grid;
      gap: 14px;
    }
    .status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .portfolio-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .diag-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .status-row {
      font-size: 1.05rem;
      line-height: 1.4;
    }
    .status-row strong {
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.1em;
    }
    .muted { color: var(--muted); }
    .metric-card, .statbox {
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px 16px;
    }
    .kicker, .label {
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.75rem;
      font-weight: 700;
      margin-bottom: 8px;
    }
    .metric {
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(1.8rem, 3vw, 2.2rem);
      font-weight: 800;
      margin: 0;
    }
    .metric.green, .ok { color: var(--green); }
    .metric.red, .bad { color: var(--red); }
    .metric.amber, .warn { color: var(--amber); }
    .sub { color: var(--muted); font-size: 0.92rem; }
    .section-title {
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.8rem;
      font-weight: 800;
      margin: 0 0 14px;
    }
    .table-wrap { overflow-x: auto; }
    table {
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
    }
    th, td {
      text-align: left;
      padding: 12px 10px;
      border-top: 1px solid #ececec;
      font-size: 0.95rem;
      vertical-align: top;
    }
    th {
      border-top: none;
      background: #f3f6f9;
      color: #56616b;
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .mono { font-family: Consolas, monospace; }
    .pill {
      display: inline-block;
      padding: 4px 9px;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 700;
      background: #eef1f4;
      color: #44505c;
    }
    .pill.ok { background: rgba(35,128,78,0.12); color: var(--green); }
    .pill.warn { background: rgba(184,121,18,0.12); color: var(--amber); }
    .pill.bad { background: rgba(214,63,63,0.12); color: var(--red); }
    .portfolio-note {
      margin-top: 14px;
      color: var(--text);
      font-size: 1.02rem;
      line-height: 1.5;
      font-weight: 600;
    }
    .alerts-list {
      display: grid;
      gap: 12px;
    }
    details.block summary, details summary {
      cursor: pointer;
      font-weight: 700;
      color: #23313f;
    }
    .diagnostics { margin-top: 14px; }
    .diag-section h3 {
      margin: 0 0 10px;
      font-size: 1.15rem;
    }
    @media (max-width: 960px) {
      .status-grid, .portfolio-grid, .diag-grid { grid-template-columns: 1fr; }
      .block-header { padding: 16px 18px; }
      .block-body { padding: 18px; }
    }
  </style>
</head>
<body>
  <div class=\"page\">
    <section class=\"block\">
      <div class=\"block-header dark\">
        <div>
          <div class=\"header-sub\">NIFTY trading monitor</div>
          <h2>System Status</h2>
        </div>
        <a class=\"header-btn\" href=\"/config\">Config</a>
      </div>
      <div class=\"block-body\">
        <div id=\"system-status\" class=\"status-grid\"></div>
      </div>
    </section>

    <section class=\"block\">
      <div class=\"block-header blue\">
        <h2>Portfolio</h2>
      </div>
      <div class=\"block-body\">
        <div id=\"portfolio-summary\" class=\"portfolio-grid\"></div>
        <div id=\"portfolio-note\" class=\"portfolio-note\">Loading portfolio view...</div>
      </div>
    </section>

    <section class=\"block\">
      <div class=\"block-body\">
        <h3 class=\"section-title\">Open Positions</h3>
        <div class=\"table-wrap\">
          <table>
            <thead>
              <tr>
                <th>Trade</th>
                <th>State</th>
                <th>Playbook</th>
                <th>Entry Time</th>
                <th>Strikes</th>
                <th>Entry</th>
                <th>Underlying</th>
                <th>P&amp;L</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody id=\"open-positions-body\"></tbody>
          </table>
        </div>
      </div>
    </section>

    <section class=\"block\">
      <div class=\"block-body\">
        <h3 class=\"section-title\">Closed Trades</h3>
        <div class=\"table-wrap\">
          <table>
            <thead>
              <tr>
                <th>Exit Time</th>
                <th>Trade</th>
                <th>What it was</th>
                <th>Reason</th>
                <th>Booked P&amp;L</th>
              </tr>
            </thead>
            <tbody id=\"closed-trades\"></tbody>
          </table>
        </div>
        <details id=\"signal-only-closures-panel\" class=\"diagnostics\"></details>
      </div>
    </section>

    <section class=\"block\">
      <div class=\"block-body\">
        <h3 class=\"section-title\">PnL History</h3>
        <div class=\"table-wrap\">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Realised</th>
                <th>Unrealised</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody id=\"pnl-history-body\"></tbody>
          </table>
        </div>
      </div>
    </section>

    <section class=\"block\">
      <div class=\"block-body\">
        <h3 class=\"section-title\">Alerts</h3>
        <div id=\"alerts-list\" class=\"alerts-list\"></div>
      </div>
    </section>

    <details class=\"block\">
      <summary style=\"padding:18px 28px;\">Show detailed diagnostics</summary>
      <div class=\"block-body\">
        <div class=\"diag-grid\" id=\"trade-strip\" style=\"margin-bottom:16px;\"></div>

        <div class=\"diag-grid\" style=\"margin-bottom:16px;\">
          <section class=\"diag-section\">
            <h3>Simple trade view</h3>
            <div class=\"diag-grid\" id=\"simple-status\"></div>
          </section>
          <section class=\"diag-section\">
            <h3>Latest trade taken</h3>
            <div class=\"diag-grid\" id=\"latest-signal\"></div>
          </section>
        </div>

        <div class=\"diag-grid\" style=\"margin-bottom:16px;\">
          <section class=\"diag-section\">
            <h3>Session scoreboard</h3>
            <div class=\"diag-grid\" id=\"scoreboard\"></div>
          </section>
          <section class=\"diag-section\">
            <h3>P&amp;L status</h3>
            <div class=\"diag-grid\" id=\"pnl-box\"></div>
          </section>
        </div>

        <section class=\"diag-section\" style=\"margin-bottom:16px;\">
          <h3>Confirmation gate</h3>
          <div class=\"diag-grid\" id=\"confirmation-gate\"></div>
        </section>

        <div class=\"diag-grid\">
          <section class=\"diag-section\">
            <h3>State since morning</h3>
            <div class=\"diag-grid\" id=\"state-history\"></div>
            <details id=\"state-history-details\" class=\"diagnostics\"></details>
          </section>
          <section class=\"diag-section\">
            <h3>Decision criteria</h3>
            <div class=\"diag-grid\" id=\"decision-criteria\"></div>
            <details id=\"decision-criteria-details\" class=\"diagnostics\"></details>
          </section>
        </div>
      </div>
    </details>
  </div>

  <script>
    function pretty(value, fallback='-') {
      return value === null || value === undefined || value === '' ? fallback : value;
    }

    function formatNumber(value, digits=2, fallback='-') {
      if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) {
        return fallback;
      }
      return Number(value).toLocaleString('en-IN', {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
    }

    function money(value, fallback='-') {
      if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) {
        return fallback;
      }
      const numeric = Number(value);
      const formatted = Math.abs(numeric).toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
      return `${numeric < 0 ? '-' : ''}₹${formatted}`;
    }

    function price(value, fallback='-') {
      return formatNumber(value, 2, fallback);
    }

    function stat(label, value, extra='') {
      return `<div class=\"statbox\"><div class=\"label\">${label}</div><div>${value}</div>${extra ? `<div class=\"sub\">${extra}</div>` : ''}</div>`;
    }

    function metricCard(label, value, tone='neutral', note='') {
      return `<article class=\"metric-card\"><div class=\"kicker\">${label}</div><div class=\"metric ${tone}\">${value}</div>${note ? `<div class=\"sub\">${note}</div>` : ''}</article>`;
    }

    function pill(text, tone='neutral') {
      return `<span class=\"pill ${tone}\">${text}</span>`;
    }

    async function refresh() {
      const res = await fetch(`/api/dashboard?ts=${Date.now()}`, { cache: 'no-store' });
      const data = await res.json();

      const runtimeRunning = Boolean(data.status.runtime_running ?? data.status.paper_eval_running);
      const modeLabel = (data.status.mode || '-').toUpperCase();
      const runtimeStatus = pretty(data.status.runtime_status, runtimeRunning ? 'LIVE' : 'STOPPED');
      const runtimeTone = runtimeStatus === 'LIVE' ? 'ok' : (runtimeStatus === 'STALE' ? 'warn' : 'bad');
      const currentState = pretty(data.headline.current_state, 'Waiting');
      const currentIdea = pretty(data.headline.display_current_playbook, 'Waiting');
      const tradeStatus = pretty(data.headline.status_text, 'Watching');

      document.getElementById('system-status').innerHTML = [
        `<div class=\"status-row\"><strong>Mode:</strong> ${modeLabel}</div>`,
        `<div class=\"status-row\"><strong>Date:</strong> ${pretty(data.session_date)} ${runtimeStatus === 'LIVE' ? '<span class=\"ok\">(Trading Day)</span>' : ''}</div>`,
        `<div class=\"status-row\"><strong>Time:</strong> ${pretty(data.status.clock_display, '-')}</div>`,
        `<div class=\"status-row\"><strong>System:</strong> ${pill(runtimeStatus, runtimeTone)}</div>`,
        `<div class=\"status-row\"><strong>Market:</strong> ${currentState}</div>`,
        `<div class=\"status-row\"><strong>Idea:</strong> ${currentIdea}</div>`,
        `<div class=\"status-row\"><strong>Session status:</strong> ${tradeStatus}</div>`,
        `<div class=\"status-row muted\"><strong>Last update:</strong> ${pretty(data.status.last_update_display || data.status.last_update)}</div>`,
      ].join('');

      const totalPnl = Number(data.portfolio.total_pnl || 0);
      const realisedPnl = Number(data.portfolio.realised_pnl || 0);
      const unrealisedPnl = Number(data.portfolio.unrealised_pnl || 0);
      document.getElementById('portfolio-summary').innerHTML = [
        metricCard('Total', money(totalPnl, '₹0.00'), totalPnl > 0 ? 'green' : (totalPnl < 0 ? 'red' : 'amber'), `${pretty(data.simple_status.trade_happening_now, 'No')} trade happening now`),
        metricCard('Realised', money(realisedPnl, '₹0.00'), realisedPnl > 0 ? 'green' : (realisedPnl < 0 ? 'red' : 'amber'), `${pretty(data.portfolio.booked_trade_count, 0)} booked trades`),
        metricCard('Unrealised', money(unrealisedPnl, '₹0.00'), unrealisedPnl > 0 ? 'green' : (unrealisedPnl < 0 ? 'red' : 'amber'), data.pnl_status.live ? 'Live MTM running' : 'Waiting for live option prices'),
        metricCard('Open Positions', pretty(data.portfolio.open_positions, 0), 'neutral', `${pretty(data.simple_status.entries_taken_today, 0)} trades today`),
      ].join('');
      document.getElementById('portfolio-note').textContent = data.headline.plain_english || 'Waiting for live evaluation.';

      const openRows = (data.open_positions || []).map(row => `
        <tr>
          <td><span class=\"mono\">${pretty(row.display_trade_id || row.trade_id, '-')}</span></td>
          <td>${pretty(row.display_state, '-')}</td>
          <td>${pretty(row.display_playbook, '-')}<div class=\"sub\">${pretty(row.display_structure, '-')}</div></td>
          <td>${pretty(row.display_entry_time, '-')}</td>
          <td>${pretty(row.display_strikes, '-')}</td>
          <td>${price(row.entry_value, '-')}</td>
          <td>${price(row.underlying_price, '-')}</td>
          <td>${row.live_available ? money(row.unrealised_pnl, '₹0.00') : 'Waiting'}</td>
          <td>${pill(pretty(row.display_status, 'Open'), row.live_available ? 'ok' : 'warn')}</td>
        </tr>`).join('');
      document.getElementById('open-positions-body').innerHTML = openRows || '<tr><td colspan="9">No open trade right now.</td></tr>';

      const closedRows = (data.closed_trades || []).map(row => `
        <tr>
          <td>${row.display_closed_at || '-'}</td>
          <td><span class=\"mono\">${row.display_trade_id || row.trade_id || ''}</span></td>
          <td>${row.display_activity_type || '-'}<div class=\"sub\">${row.display_playbook || '-'}</div></td>
          <td>${row.display_reason || '-'}<div class=\"sub\">${row.activity_note || ''}</div></td>
          <td>${money(row.realised_pnl, '₹0.00')}</td>
        </tr>`).join('');
      const hiddenSignalCount = (data.signal_only_closed_trades || []).length;
      const emptyMessage = hiddenSignalCount > 0
        ? `<tr><td colspan="5">No booked paper-trade closures for this session. ${hiddenSignalCount} signal-only closures are hidden below.</td></tr>`
        : '<tr><td colspan="5">No current-session closures yet.</td></tr>';
      document.getElementById('closed-trades').innerHTML = closedRows || emptyMessage;

      const signalOnlyRows = (data.signal_only_closed_trades || []).map(row => `
        <tr>
          <td><code>${row.display_trade_id || row.trade_id || ''}</code></td>
          <td>${row.display_activity_type || '-'}<div class=\"sub\">${row.display_playbook || '-'}</div></td>
          <td>${row.display_closed_at || '-'}</td>
          <td>${row.display_reason || '-'}<div class=\"sub\">${row.activity_note || ''}</div></td>
          <td>${money(row.realised_pnl, '₹0.00')}</td>
        </tr>`).join('');
      document.getElementById('signal-only-closures-panel').innerHTML = hiddenSignalCount > 0
        ? `<summary>Show ${hiddenSignalCount} signal-only closures</summary>
            <table style=\"margin-top:10px;\">
              <thead>
                <tr>
                  <th>Signal ID</th>
                  <th>What it was</th>
                  <th>Closed at</th>
                  <th>Why it ended</th>
                  <th>Booked P&amp;L</th>
                </tr>
              </thead>
              <tbody>${signalOnlyRows}</tbody>
            </table>`
        : '';

      const pnlRows = (data.pnl_history || []).map(row => `
        <tr>
          <td>${pretty(row.time, '-')}</td>
          <td>${money(row.realised, '₹0.00')}</td>
          <td>${money(row.unrealised, '₹0.00')}</td>
          <td>${money(row.total, '₹0.00')}</td>
        </tr>`).join('');
      document.getElementById('pnl-history-body').innerHTML = pnlRows || '<tr><td colspan="4">PnL history will appear here.</td></tr>';

      const alerts = (data.alerts || []).map(message => `<div class="statbox">${message}</div>`).join('');
      document.getElementById('alerts-list').innerHTML = alerts || '<div class="statbox">No current alerts.</div>';

      document.getElementById('trade-strip').innerHTML = [
        stat('Current status', pretty(data.trade_strip.status)),
        stat('Last closure reason', pretty(data.trade_strip.last_exit_reason)),
        stat('Most recent session closure', pretty(data.trade_strip.display_last_closed_trade_id || data.trade_strip.last_closed_trade_id, '-'), pretty(data.trade_strip.status_note)),
        stat('Closure events', pretty(data.trade_strip.closed_trade_count, 0), `${pretty(data.pnl_status.booked_trade_count, 0)} booked trades, ${pretty(data.pnl_status.signal_only_count, 0)} signal-only`),
      ].join('');

      document.getElementById('simple-status').innerHTML = [
        stat('Trades taken today', pretty(data.simple_status.entries_taken_today, 0), 'Entries recorded since morning'),
        stat('Trade happening now?', pretty(data.simple_status.trade_happening_now, 'No'), pretty(data.simple_status.trade_status, '-')),
        stat('Current trade', pretty(data.simple_status.display_current_trade_id || data.simple_status.current_trade_id, '-'), `${pretty(data.simple_status.current_trade_playbook, 'Waiting')} · ${pretty(data.simple_status.progress_summary, '-')}`),
        stat('Last closed trade', pretty(data.simple_status.display_last_closed_trade_id || data.simple_status.last_closed_trade_id, '-'), `${money(data.simple_status.last_closed_pnl, '₹0.00')} · ${pretty(data.simple_status.last_closed_reason, '-')}`),
      ].join('');

      document.getElementById('latest-signal').innerHTML = [
        stat('Signal ID', `<span class=\"mono\">${pretty(data.latest_signal.display_trade_id || data.latest_signal.trade_id)}</span>`),
        stat('Market view', pretty(data.latest_signal.state)),
        stat('Current idea', pretty(data.latest_signal.display_playbook, 'Waiting')),
        stat('Structure', pretty(data.latest_signal.display_structure, 'Waiting')),
        stat('Underlying at signal', price(data.latest_signal.underlying_price)),
        stat('Strikes', pretty(data.latest_signal.display_strikes)),
        stat('Expiry', pretty(data.latest_signal.display_expiry)),
        stat('Reason', pretty(data.latest_signal.display_reason, 'Signal recorded')),
      ].join('');

      document.getElementById('scoreboard').innerHTML = [
        stat('Lots', pretty(data.latest_signal.lots || 1, 1)),
        stat('Live MTM (₹)', data.pnl_status.live ? money(data.pnl_status.unrealised_pnl) : '-', data.pnl_status.live ? `Updated ${pretty(data.pnl_status.last_update_display || data.pnl_status.last_update)}` : 'Will appear once all option legs are being marked live'),
        stat('MTM points', data.pnl_status.live ? price(data.pnl_status.mtm_points) : '-'),
        stat('Booked for session (₹)', money(data.pnl_status.realised_pnl_today, '₹0.00'), `${pretty(data.pnl_status.booked_trade_count, 0)} booked trades, ${pretty(data.pnl_status.signal_only_count, 0)} signal-only`),
      ].join('');

      document.getElementById('pnl-box').innerHTML = [
        stat('P&L mode', pretty(data.pnl_status.mode).replaceAll('_', ' ')),
        stat('Live P&L available?', data.pnl_status.live ? 'Yes' : 'Not yet'),
        stat('Live underlying', data.pnl_status.live ? price(data.pnl_status.underlying_price) : '-'),
        stat('Entry credit / debit', data.pnl_status.live ? `${price(data.pnl_status.entry_credit)} / ${price(data.pnl_status.entry_debit)}` : '-'),
        stat('Current close value', data.pnl_status.live ? price(data.pnl_status.current_close_value) : '-'),
        stat('Booked for shown session', money(data.pnl_status.realised_pnl_today, '₹0.00'), `${pretty(data.pnl_status.booked_trade_count, 0)} booked trades, ${pretty(data.pnl_status.signal_only_count, 0)} signal-only`),
        stat('Why it looks this way', pretty(data.pnl_status.reason), data.pnl_status.live ? 'Marked from the current option-leg prices.' : pretty(data.pnl_status.display_scope, 'Current session only')),
      ].join('');

      document.getElementById('confirmation-gate').innerHTML = [
        stat('Gate status', pretty(data.confirmation_gate.summary)),
        stat('Entry rule', `${pretty(data.confirmation_gate.entry_confirmations_required, 0)} matching 1-minute checks`),
        stat('Current candidate', pretty(data.confirmation_gate.display_candidate_state, 'Waiting'), `${pretty(data.confirmation_gate.candidate_count, 0)}/${pretty(data.confirmation_gate.entry_confirmations_required, 0)} matched`),
        stat('Active state', pretty(data.confirmation_gate.display_active_state, 'No active trade')),
        stat('Exit rule', `${pretty(data.confirmation_gate.exit_confirmations_required, 0)} non-matching 1-minute checks`),
        stat('Exit progress', `${pretty(data.confirmation_gate.opposite_count, 0)}/${pretty(data.confirmation_gate.exit_confirmations_required, 0)}`, pretty(data.confirmation_gate.display_reason, '-')),
      ].join('');

      document.getElementById('state-history').innerHTML = [
        stat('Current state', pretty(data.state_history.current_state, 'Waiting')),
        stat('Checks since morning', pretty(data.state_history.entry_count, 0), `${pretty(data.state_history.first_seen, '-')} → ${pretty(data.state_history.last_seen, '-')}`),
        stat('Tradeable checks', `${pretty(data.state_history.tradeable_count, 0)}/${pretty(data.state_history.entry_count, 0)}`),
        stat('State mix', pretty(data.state_history.summary, 'No state history yet')),
      ].join('');

      document.getElementById('decision-criteria').innerHTML = [
        stat('Decision now', pretty(data.decision_context.decision_status, 'No trade'), pretty(data.decision_context.summary, '-')),
        stat('Latest state', pretty(data.decision_context.display_state, 'Waiting'), `Tradeable: ${pretty(data.decision_context.display_tradeable, 'No')}`),
        stat('Edge reason', pretty(data.decision_context.display_edge_reason, '-'), `Ambiguity: ${pretty(data.decision_context.display_ambiguity, '-')}`),
        stat('Selected playbook', pretty(data.decision_context.display_playbook, 'No Trade'), `Confidence: ${pretty(data.decision_context.confidence, '-')}`),
      ].join('');

      const criteriaRows = (data.decision_context.criteria_checks || []).map(row => `
        <tr>
          <td>${row.label || '-'}</td>
          <td>${row.passed ? 'Pass' : 'Not met'}</td>
          <td>${row.detail || '-'}</td>
        </tr>`).join('');
      document.getElementById('decision-criteria-details').innerHTML = criteriaRows
        ? `<summary>Show current criteria checks</summary>
            <table style=\"margin-top:10px;\">
              <thead>
                <tr>
                  <th>Check</th>
                  <th>Status</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>${criteriaRows}</tbody>
            </table>`
        : '<summary>No criteria checks yet</summary>';

      const stateRows = (data.state_history.entries || []).map(row => `
        <tr>
          <td>${row.display_time || '-'}</td>
          <td>${row.display_state || row.state || '-'}</td>
          <td>${pretty(row.confidence, '-')}</td>
          <td>${row.display_tradeable || '-'}</td>
        </tr>`).join('');
      document.getElementById('state-history-details').innerHTML = stateRows
        ? `<summary>Show recent 1-minute state checks</summary>
            <table style=\"margin-top:10px;\">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>State</th>
                  <th>Confidence</th>
                  <th>Tradeable?</th>
                </tr>
              </thead>
              <tbody>${stateRows}</tbody>
            </table>`
        : '<summary>No state history yet</summary>';
    }

    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>"""


def render_config_page() -> str:
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Monitor Config</title>
  <style>
    body {{ margin: 0; background: #ececec; color: #1f252b; font-family: 'Segoe UI', Arial, sans-serif; }}
    .page {{ max-width: 900px; margin: 24px auto; padding: 0 16px; }}
    .card {{ background: #f8f8f8; border: 1px solid #cfcfcf; border-radius: 18px; overflow: hidden; }}
    .head {{ background: linear-gradient(90deg, #171d24, #202833); color: #fff; padding: 18px 24px; display: flex; justify-content: space-between; align-items: center; }}
    .head h1 {{ margin: 0; font-family: Georgia, 'Times New Roman', serif; }}
    .body {{ padding: 20px 24px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #ddd; }}
    th, td {{ text-align: left; padding: 12px 10px; border-top: 1px solid #ececec; }}
    th {{ border-top: none; background: #f3f6f9; text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.75rem; color: #5c6770; }}
    a {{ color: #156ff6; text-decoration: none; font-weight: 600; }}
  </style>
</head>
<body>
  <div class=\"page\">
    <section class=\"card\">
      <div class=\"head\">
        <h1>Config</h1>
        <a href=\"/\" style=\"color:#fff;\">Back to monitor</a>
      </div>
      <div class=\"body\">
        <table>
          <thead>
            <tr><th>Setting</th><th>Value</th></tr>
          </thead>
          <tbody>
            <tr><td>Execution mode</td><td>{APP_CONFIG.trading.execution_mode.value}</td></tr>
            <tr><td>Live trading enabled</td><td>{APP_CONFIG.trading.live_trading_enabled}</td></tr>
            <tr><td>Entry confirmations required</td><td>{APP_CONFIG.trading.entry_confirmations_required}</td></tr>
            <tr><td>Exit confirmations required</td><td>{APP_CONFIG.trading.exit_confirmations_required}</td></tr>
            <tr><td>Monitor freshness seconds</td><td>{FRESHNESS_SEC}</td></tr>
            <tr><td>Host / Port</td><td>{DEFAULT_HOST}:{DEFAULT_PORT}</td></tr>
            <tr><td>Runtime log</td><td>{RUNTIME_LOG_PATH}</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</body>
</html>"""


class MonitoringHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/favicon.ico", "/static/favicon.ico"}:
            if FAVICON_PATH.exists():
                body = FAVICON_PATH.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/x-icon")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Favicon not found")
            return
        if parsed.path == "/api/dashboard":
            self._send_json(build_dashboard_payload())
            return
        if parsed.path == "/config":
            body = render_config_page().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path in {"/", "/index.html"}:
            body = render_index().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/health":
            self._send_json({"ok": True})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer((DEFAULT_HOST, DEFAULT_PORT), MonitoringHandler)
    print(f"NIFTY trading monitor running at http://{DEFAULT_HOST}:{DEFAULT_PORT}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
