import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.logger import get_logger
from scripts.utils import fetch_ltp_map


IST = ZoneInfo("Asia/Kolkata")
logger = get_logger("paper_mtm")

BASE_DIR = Path(__file__).resolve().parents[1]

OPEN_POS_FILE = BASE_DIR / "data" / "open_position.json"
RESULTS_FILE = BASE_DIR / "data" / "results" / "system_pnl.csv"
LAST_STATE_FILE = BASE_DIR / "data" / "last_state.json"
PNL_STATE_FILE = BASE_DIR / "data" / "pnl_state.json"

RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)


# ==================================================
# STATE HELPERS
# ==================================================
def _safe_load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return default


def load_last_state():
    return _safe_load_json(LAST_STATE_FILE, {})


def save_last_state(state: dict):
    with LAST_STATE_FILE.open("w") as f:
        json.dump(state, f)


def load_realised() -> float:
    data = _safe_load_json(PNL_STATE_FILE, {})
    return float(data.get("realised_today", 0.0))


def save_realised(val: float):
    with PNL_STATE_FILE.open("w") as f:
        json.dump({"realised_today": float(val)}, f)


# ==================================================
def load_open_position():
    pos = _safe_load_json(OPEN_POS_FILE, None)
    if not pos or pos.get("status") != "OPEN":
        return None
    return pos


# ==================================================
def append_row(row):

    write_header = not RESULTS_FILE.exists()

    with RESULTS_FILE.open("a") as f:

        if write_header:
            f.write(
                "timestamp,trade_id,state,regime,strike,expiry,"
                "realised,unrealised,total\n"
            )

        f.write(",".join(map(str, row)) + "\n")


# ==================================================
# CORE ENGINE
# ==================================================
def run():

    now_dt = datetime.now(IST)
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    realised_today = load_realised()

    pos = load_open_position()
    last_state = load_last_state()

    prev_trade = last_state.get("trade_id")
    last_write_ts = last_state.get("last_write_ts")

    # ---- HARD GUARD: one write per minute ----
    if last_write_ts == now:
        return

    # ==================================================
    # NO POSITION
    # ==================================================
    if not pos:

        state = "FLAT"
        trade_id = ""
        regime = ""
        strike = ""
        expiry = ""
        unrealised = 0.0

        # detect EXIT transition
        if prev_trade:
            last_unrealised = float(last_state.get("last_unrealised", 0.0))
            realised_today += last_unrealised
            save_realised(realised_today)
            state = "EXIT"

        append_row([
            now,
            trade_id,
            state,
            regime,
            strike,
            expiry,
            f"{realised_today:.2f}",
            f"{unrealised:.2f}",
            f"{realised_today:.2f}",
        ])

        save_last_state({"last_write_ts": now})
        return

    # ==================================================
    # OPEN POSITION
    # ==================================================
    trade_id = pos["trade_id"]
    regime = pos["regime"]
    strike = pos["strike"]
    expiry = pos["expiry"]
    legs = pos.get("legs", [])

    state = "ENTRY" if trade_id != prev_trade else "OPEN"

    security_ids = [int(l["security_id"]) for l in legs]
    ltp_map = fetch_ltp_map(security_ids)

    LOT_SIZE = 50
    unrealised = 0.0

    for leg in legs:
        sid = int(leg["security_id"])
        entry_price = float(leg["entry_price"])
        lots = int(leg["lots"])

        ltp = ltp_map.get(sid)
        if ltp is None:
            continue

        qty = LOT_SIZE * lots
        unrealised += (entry_price - ltp) * qty  # short MTM

    total = realised_today + unrealised

    append_row([
        now,
        trade_id,
        state,
        regime,
        strike,
        expiry,
        f"{realised_today:.2f}",
        f"{unrealised:.2f}",
        f"{total:.2f}",
    ])

    save_last_state({
        "trade_id": trade_id,
        "last_unrealised": unrealised,
        "last_write_ts": now,
    })

    logger.info(
        f"{state} | {regime} | strike={strike} exp={expiry} | "
        f"Realised={realised_today:.2f} "
        f"Unrealised={unrealised:.2f} "
        f"Total={total:.2f}"
    )