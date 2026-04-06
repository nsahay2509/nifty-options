import csv
from datetime import datetime
from pathlib import Path

from config import APP_CONFIG
from scripts.clock import get_clock
from scripts.logger import get_logger
from scripts.models import OpenPosition
from scripts.state_utils import atomic_write_json, safe_load_json, safe_load_model_json


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = DATA_DIR / "results"
LOGGER = get_logger("dashboard_state")

DASHBOARD_STATE_FILE = BASE_DIR / APP_CONFIG.monitoring.dashboard_state_file
SIGNAL_STATE_FILE = DATA_DIR / "signal_state.json"
OPEN_POSITIONS = {
    "sell": DATA_DIR / "open_position.json",
    "buy": DATA_DIR / "open_position_buy.json",
}
SYSTEM_PNL = {
    "sell": RESULTS_DIR / "system_pnl.csv",
    "buy": RESULTS_DIR / "system_pnl_buy.csv",
}


def read_latest_csv_dict(path: Path):
    if not path.exists():
        return None

    with path.open() as f:
        rows = list(csv.DictReader(f))

    return rows[-1] if rows else None


def read_open_position(path: Path):
    position = safe_load_model_json(path, None, OpenPosition.from_dict)
    if not position or position.status != "OPEN":
        return None
    return position.to_dict()


def format_signal_time(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S IST")
    except ValueError:
        return value


def build_dashboard_state(*, cycle_started_at: str | None = None, updater_ok: bool | None = None, clock=None):
    active_clock = clock or get_clock()
    generated_at = active_clock.now().strftime("%Y-%m-%d %H:%M:%S")
    signal_state = safe_load_json(SIGNAL_STATE_FILE, {})

    positions = {
        side: read_open_position(path)
        for side, path in OPEN_POSITIONS.items()
    }

    pnl = {}
    combined_total = 0.0
    for side, path in SYSTEM_PNL.items():
        latest = read_latest_csv_dict(path) or {}
        pnl[side] = {
            "timestamp": latest.get("timestamp", ""),
            "state": latest.get("state", "UNKNOWN"),
            "trade_id": latest.get("trade_id", ""),
            "realised": float(latest.get("realised", 0.0) or 0.0),
            "unrealised": float(latest.get("unrealised", 0.0) or 0.0),
            "total": float(latest.get("total", 0.0) or 0.0),
        }
        combined_total += pnl[side]["total"]

    state = {
        "generated_at": generated_at,
        "cycle_started_at": cycle_started_at or generated_at,
        "updater_ok": updater_ok,
        "experiment": APP_CONFIG.regime.experiment_name,
        "signal": {
            "last_regime": signal_state.get("last_regime", "WAIT"),
            "candidate_regime": signal_state.get("candidate_regime", "WAIT"),
            "candidate_count": signal_state.get("candidate_count", 0),
            "confirmed_regime": signal_state.get("confirmed_regime", "WAIT"),
            "last_signal_time": format_signal_time(signal_state.get("last_signal_time")),
        },
        "positions": positions,
        "pnl": {
            "sell": pnl["sell"],
            "buy": pnl["buy"],
        },
    }
    return state


def write_dashboard_state(*, cycle_started_at: str | None = None, updater_ok: bool | None = None, clock=None):
    payload = build_dashboard_state(
        cycle_started_at=cycle_started_at,
        updater_ok=updater_ok,
        clock=clock,
    )
    atomic_write_json(DASHBOARD_STATE_FILE, payload, indent=2)
    LOGGER.info(f"DASHBOARD_STATE_UPDATED | file={DASHBOARD_STATE_FILE}")
    return payload
