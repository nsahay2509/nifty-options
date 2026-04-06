from __future__ import annotations

import csv
import json
import os
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
    quantity_raw = row.get("quantity", "0")
    try:
        lots = int(float(quantity_raw or 0))
    except ValueError:
        lots = 0

    underlying_price = context.get("underlying_price")
    if isinstance(underlying_price, (int, float)):
        underlying_price = round(float(underlying_price), 2)

    session_date = str(row.get("session_date", ""))
    return {
        **row,
        "display_trade_id": clean_trade_id(str(row.get("trade_id", ""))),
        "display_state": nice_label(row.get("state_at_entry", "")),
        "display_playbook": display_label(str(row.get("playbook", ""))),
        "display_structure": display_label(str(row.get("structure_type", ""))),
        "display_reason": display_reason(str(row.get("exit_reason", ""))),
        "display_expiry": resolve_expiry_label(str(row.get("expiry", "")), session_date),
        "underlying_price": underlying_price,
        "paper_mode": bool(context.get("paper_mode", False)),
        "strikes": strikes,
        "display_strikes": ", ".join(str(int(strike)) if float(strike).is_integer() else str(strike) for strike in strikes) if strikes else "-",
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
    is_fresh = bool(last_update_ts and (now_ts - last_update_ts) <= FRESHNESS_SEC)
    last_update_iso = (
        datetime.fromtimestamp(last_update_ts, tz=timezone.utc).astimezone().isoformat()
        if last_update_ts
        else ""
    )

    latest_signal = recent_records[0] if recent_records else {}
    latest_state = str(latest_signal.get("state_at_entry", ""))
    latest_playbook = str(latest_signal.get("playbook", ""))
    has_recent_signal = bool(is_fresh and latest_signal)
    live_mtm_enabled = bool(live_mtm.get("live", False)) and is_fresh
    recent_closed = live_mtm.get("recent_closed", []) if isinstance(live_mtm.get("recent_closed", []), list) else []
    last_closed = recent_closed[0] if recent_closed else {}

    calendar = MarketCalendar()
    market_phase = calendar.classify_timestamp()
    runtime_status = "LIVE" if is_fresh else ("STALE" if market_phase == "open" else "STOPPED")

    if live_mtm_enabled:
        strip_status = "OPEN"
    elif int(live_mtm.get("closed_trade_count", 0) or 0) > 0:
        strip_status = "CLOSED"
    elif is_fresh:
        strip_status = "WATCHING"
    else:
        strip_status = "STALE"

    if live_mtm_enabled:
        status_text = "Trade active"
    elif is_fresh:
        status_text = "Watching for setup"
    elif runtime_status == "STALE":
        status_text = "System stale"
    else:
        status_text = "System stopped"

    closed_trades = [
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
            "realised_pnl": float(item.get("realised_pnl", 0.0) or 0.0),
            "mtm_points": float(item.get("mtm_points", 0.0) or 0.0),
        }
        for item in recent_closed
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
        },
        "session_date": summary.get("session_date", ""),
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
            "current_state": nice_label(latest_state),
            "current_playbook": latest_playbook,
            "display_current_playbook": latest_signal.get("display_playbook", display_label(latest_playbook)),
            "current_structure": latest_signal.get("structure_type", ""),
            "display_current_structure": latest_signal.get("display_structure", display_label(str(latest_signal.get("structure_type", "")))),
            "plain_english": describe_current_view(nice_label(latest_state), latest_playbook, live_mtm_enabled, runtime_status),
            "trade_underway": live_mtm_enabled,
            "recent_signal_seen": has_recent_signal,
        },
        "trade_strip": {
            "status": strip_status,
            "status_note": "Trade is currently open" if strip_status == "OPEN" else ("Last trade is closed" if strip_status == "CLOSED" else "System is watching for the next setup"),
            "last_exit_reason": display_reason(str(last_closed.get("exit_reason", "")), default="No exits yet"),
            "last_closed_trade_id": str(last_closed.get("trade_id", "")),
            "display_last_closed_trade_id": clean_trade_id(str(last_closed.get("trade_id", ""))),
            "closed_trade_count": int(live_mtm.get("closed_trade_count", 0) or 0),
        },
        "pnl_status": {
            "live": live_mtm_enabled,
            "mode": str(live_mtm.get("mode", "live_mtm" if live_mtm_enabled else "signal_only")),
            "reason": str(
                live_mtm.get(
                    "reason",
                    "Current rebuild logs signals and live marks using the active execution mode.",
                )
            ),
            "trade_id": str(live_mtm.get("trade_id", "")),
            "display_trade_id": clean_trade_id(str(live_mtm.get("trade_id", ""))),
            "entry_credit": float(live_mtm.get("entry_credit", 0.0) or 0.0),
            "entry_debit": float(live_mtm.get("entry_debit", 0.0) or 0.0),
            "current_close_value": float(live_mtm.get("current_close_value", 0.0) or 0.0),
            "underlying_price": float(live_mtm.get("underlying_price", 0.0) or 0.0),
            "mtm_points": float(live_mtm.get("mtm_points", 0.0) or 0.0),
            "unrealised_pnl": float(live_mtm.get("unrealised_pnl", 0.0) or 0.0),
            "realised_pnl_today": float(live_mtm.get("realised_pnl_today", 0.0) or 0.0),
            "closed_trade_count": int(live_mtm.get("closed_trade_count", 0) or 0),
            "last_update": str(live_mtm.get("last_update", "")),
            "last_update_display": format_display_timestamp(live_mtm.get("last_update", "")),
        },
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
        "recent_records": recent_records,
        "closed_trades": closed_trades,
    }


def render_index() -> str:
    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>NIFTY Trading Monitor</title>
  <style>
    :root {
      --bg: #f4f1e8;
      --panel: rgba(255, 252, 246, 0.92);
      --ink: #182126;
      --muted: #5f6c72;
      --line: rgba(24, 33, 38, 0.12);
      --green: #1d7a4a;
      --green-soft: rgba(29, 122, 74, 0.12);
      --red: #b14332;
      --red-soft: rgba(177, 67, 50, 0.12);
      --amber: #9b6a11;
      --amber-soft: rgba(155, 106, 17, 0.14);
      --blue: #215d7a;
      --blue-soft: rgba(33, 93, 122, 0.12);
      --shadow: 0 18px 40px rgba(48, 39, 28, 0.10);
      --radius: 20px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(33, 93, 122, 0.18), transparent 24%),
        radial-gradient(circle at top right, rgba(29, 122, 74, 0.14), transparent 28%),
        linear-gradient(180deg, #fbf7ef 0%, var(--bg) 100%);
    }
    .page { max-width: 1320px; margin: 0 auto; padding: 24px 16px 40px; }
    .hero { display: grid; grid-template-columns: 1.6fr 0.9fr; gap: 16px; margin-bottom: 18px; }
    .card, .panel { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); }
    .hero-main, .hero-side, .mini, .panel { padding: 18px 20px; }
    .eyebrow { margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.12em; font-size: 0.72rem; color: var(--muted); font-weight: 700; }
    h1 { margin: 0 0 8px; font-size: clamp(2rem, 3vw, 3rem); line-height: 1; }
    .hero-copy { color: var(--muted); max-width: 70ch; font-size: 1rem; }
    .chip-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
    .chip { display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 999px; border: 1px solid var(--line); background: rgba(255,255,255,0.68); font-size: 0.9rem; }
    .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--amber); box-shadow: 0 0 0 4px var(--amber-soft); }
    .dot.ok { background: var(--green); box-shadow: 0 0 0 4px var(--green-soft); }
    .dot.bad { background: var(--red); box-shadow: 0 0 0 4px var(--red-soft); }
    .hero-big { font-size: 2rem; font-weight: 800; margin: 0; }
    .hero-note { margin-top: 8px; color: var(--muted); }
    .grid-4, .grid-2 { display: grid; gap: 16px; margin-bottom: 18px; }
    .grid-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .label { color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; font-size: 0.72rem; font-weight: 700; margin-bottom: 8px; }
    .value { font-size: 1.8rem; font-weight: 800; margin: 0 0 6px; }
    .sub { color: var(--muted); font-size: 0.92rem; }
    .ok { color: var(--green); }
    .warn { color: var(--amber); }
    .bad { color: var(--red); }
    .panel h3 { margin: 0 0 10px; }
    .two-col { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .statbox { padding: 12px; border-radius: 14px; background: rgba(255,255,255,0.72); border: 1px solid var(--line); }
    .mono { font-family: Consolas, monospace; }
    pre { white-space: pre-wrap; background: rgba(255,255,255,0.55); padding: 12px; border-radius: 12px; overflow: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--line); font-size: 0.92rem; vertical-align: top; }
    th { color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.72rem; }
    @media (max-width: 1000px) { .hero, .grid-4, .grid-2, .two-col { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class=\"page\">
    <section class=\"hero\">
      <div class=\"card hero-main\">
        <p class=\"eyebrow\">NIFTY trading monitor</p>
        <h1>What is happening right now?</h1>
        <div class=\"hero-copy\" id=\"plain-english\">Loading live trading story...</div>
        <div class=\"chip-row\" id=\"chip-row\"></div>
      </div>
      <div class=\"card hero-side\">
        <div class=\"label\">Trade status</div>
        <p id=\"status-big\" class=\"hero-big\">Loading</p>
        <div class=\"label\" style=\"margin-top:14px\">Current market read</div>
        <p id=\"state-big\" class=\"value\">-</p>
        <div id=\"idea-note\" class=\"hero-note\">Waiting for current idea...</div>
      </div>
    </section>
    <section class="panel" style="margin-bottom:18px;">
      <h3>Trade status</h3>
      <div class="two-col" id="trade-strip"></div>
    </section>
    <section class=\"grid-4\">
      <article class=\"card mini\"><div class=\"label\">Mode</div><div id=\"mode\" class=\"value\">-</div><div class=\"sub\">Current execution mode</div></article>
      <article class=\"card mini\"><div class=\"label\">Session date</div><div id=\"session\" class=\"value\">-</div><div class=\"sub\">Current trading day</div></article>
      <article class=\"card mini\"><div class=\"label\">Signals today</div><div id=\"count\" class=\"value\">0</div><div class=\"sub\">Evaluations recorded</div></article>
      <article class=\"card mini\"><div class=\"label\">Last update</div><div id=\"updated\" class=\"sub\">-</div></article>
    </section>

    <section class=\"grid-2\">
      <article class=\"panel\">
        <h3>Latest signal</h3>
        <div class=\"two-col\" id=\"latest-signal\"></div>
      </article>
      <article class=\"panel\">
        <h3>Session scoreboard</h3>
        <div class=\"two-col\" id=\"scoreboard\"></div>
      </article>
    </section>

    <section class="panel" style="margin-bottom:18px;">
      <h3>P&L status</h3>
      <div class="two-col" id="pnl-box"></div>
    </section>

    <section class="panel">
      <h3>Closed trades</h3>
      <table>
        <thead>
          <tr>
            <th>Trade ID</th>
            <th>Strategy</th>
            <th>Closed at</th>
            <th>Exit reason</th>
            <th>Booked P&amp;L</th>
          </tr>
        </thead>
        <tbody id="closed-trades"></tbody>
      </table>
    </section>
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

    async function refresh() {
      const res = await fetch(`/api/dashboard?ts=${Date.now()}`, { cache: 'no-store' });
      const data = await res.json();

      const runtimeRunning = Boolean(data.status.runtime_running ?? data.status.paper_eval_running);
      const modeLabel = (data.status.mode || '-').toUpperCase();
      const runtimeStatus = pretty(data.status.runtime_status, runtimeRunning ? 'LIVE' : 'STOPPED');
      const runtimeStatusText = runtimeStatus.charAt(0) + runtimeStatus.slice(1).toLowerCase();
      const systemDotClass = runtimeStatus === 'LIVE' ? 'ok' : (runtimeStatus === 'STALE' ? '' : 'bad');

      document.getElementById('plain-english').textContent = data.headline.plain_english || 'Waiting for live evaluation.';
      document.getElementById('status-big').textContent = data.headline.status_text || 'Watching';
      document.getElementById('status-big').className = `hero-big ${data.headline.trade_underway ? 'ok' : (runtimeStatus === 'STALE' ? 'warn' : (runtimeRunning ? 'warn' : 'bad'))}`;
      document.getElementById('state-big').textContent = pretty(data.headline.current_state, 'Waiting');
      document.getElementById('idea-note').textContent = data.headline.display_current_playbook
        ? `Current idea: ${data.headline.display_current_playbook}.`
        : 'No active structure right now.';

      document.getElementById('mode').textContent = modeLabel;
      document.getElementById('session').textContent = pretty(data.session_date);
      document.getElementById('count').textContent = String(data.summary.total_trades ?? 0);
      document.getElementById('updated').textContent = pretty(data.status.last_update_display || data.status.last_update);

      document.getElementById('chip-row').innerHTML = [
        `<span class="chip"><span class="dot ${systemDotClass}"></span><strong>System:</strong> ${runtimeStatusText}</span>`,
        `<span class="chip"><span class="dot ok"></span><strong>Mode:</strong> ${modeLabel}</span>`,
        `<span class="chip"><span class="dot"></span><strong>Market read:</strong> ${pretty(data.headline.current_state)}</span>`,
        `<span class="chip"><span class="dot"></span><strong>Idea:</strong> ${pretty(data.headline.display_current_playbook, 'Waiting')}</span>`
      ].join('');

      document.getElementById('trade-strip').innerHTML = [
        stat('Open / Closed', pretty(data.trade_strip.status)),
        stat('Last exit reason', pretty(data.trade_strip.last_exit_reason)),
        stat('Last closed trade', pretty(data.trade_strip.display_last_closed_trade_id || data.trade_strip.last_closed_trade_id), pretty(data.trade_strip.status_note)),
        stat('Closed count', pretty(data.trade_strip.closed_trade_count, 0)),
      ].join('');

      document.getElementById('latest-signal').innerHTML = [
        stat('Trade ID', `<span class="mono">${pretty(data.latest_signal.display_trade_id || data.latest_signal.trade_id)}</span>`),
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
        stat('Booked today (₹)', money(data.pnl_status.realised_pnl_today, '₹0.00'), `${data.pnl_status.closed_trade_count ?? 0} closed trades`),
      ].join('');

      document.getElementById('pnl-box').innerHTML = [
        stat('P&L mode', pretty(data.pnl_status.mode).replaceAll('_', ' ')),
        stat('Live P&L available?', data.pnl_status.live ? 'Yes' : 'Not yet'),
        stat('Live underlying', data.pnl_status.live ? price(data.pnl_status.underlying_price) : '-'),
        stat('Entry credit / debit', data.pnl_status.live ? `${price(data.pnl_status.entry_credit)} / ${price(data.pnl_status.entry_debit)}` : '-'),
        stat('Current close value', data.pnl_status.live ? price(data.pnl_status.current_close_value) : '-'),
        stat('Booked today', money(data.pnl_status.realised_pnl_today, '₹0.00'), `${pretty(data.pnl_status.closed_trade_count, 0)} completed exits`),
        stat('Why it looks this way', pretty(data.pnl_status.reason), data.pnl_status.live ? 'Marked from the current option-leg prices.' : 'This page currently shows the booked total while waiting for the next live setup.'),
      ].join('');

      const closedRows = (data.closed_trades || []).map(row => `
        <tr>
          <td><code>${row.display_trade_id || row.trade_id || ''}</code></td>
          <td>${row.display_playbook || '-'}</td>
          <td>${row.display_closed_at || '-'}</td>
          <td>${row.display_reason || '-'}</td>
          <td>${money(row.realised_pnl, '₹0.00')}</td>
        </tr>`).join('');
      document.getElementById('closed-trades').innerHTML = closedRows || '<tr><td colspan="5">No closed trades yet.</td></tr>';
    }

    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>"""


class MonitoringHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/dashboard":
            self._send_json(build_dashboard_payload())
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
