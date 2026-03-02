


# python -m scripts.update_nifty_spot

import os
import json
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from scripts.utils import get_dhan_headers
from scripts.logger import get_logger


# ---------------- CONFIG ----------------
IST = ZoneInfo("Asia/Kolkata")

logger = get_logger("spot_updater")

URL = "https://api.dhan.co/v2/charts/intraday"

SECURITY_ID = "13"
EXCHANGE_SEGMENT = "IDX_I"
INSTRUMENT = "INDEX"
INTERVAL = "1"

REQUEST_TIMEOUT = 10

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(BASE_DIR, "data", "spot")
os.makedirs(OUTDIR, exist_ok=True)


# ---------------- HELPERS ----------------
def today_file():
    today = datetime.now(IST).strftime("%Y-%m-%d")
    return os.path.join(OUTDIR, f"{today}.jsonl")


def fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)


def last_completed_minute() -> datetime:
    now = datetime.now(IST)
    return now.replace(second=0, microsecond=0) - timedelta(minutes=1)


def read_last_timestamp(path: str) -> datetime | None:
    if not os.path.exists(path):
        return None

    try:
        with open(path, "rb") as f:
            # handle small files safely
            try:
                f.seek(-512, os.SEEK_END)
            except OSError:
                f.seek(0)

            lines = f.readlines()
            if not lines:
                return None

            last_line = lines[-1].decode("utf-8", errors="ignore").strip()
            if not last_line:
                return None

        row = json.loads(last_line)
        ts = row.get("ts")
        return parse_ts(ts) if ts else None

    except Exception:
        return None


def append_row(path: str, row: dict):
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


# ---------------- API ----------------
def fetch_candle(ts_dt: datetime) -> dict | None:

    payload = {
        "securityId": SECURITY_ID,
        "exchangeSegment": EXCHANGE_SEGMENT,
        "instrument": INSTRUMENT,
        "interval": INTERVAL,
        "oi": False,
        "fromDate": fmt_ts(ts_dt),
        "toDate": fmt_ts(ts_dt),
    }

    headers = get_dhan_headers()
    headers["Accept"] = "application/json"

    try:
        r = requests.post(URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        logger.warning(f"API error: {e}")
        return None

    if r.status_code != 200:
        logger.warning(f"API status {r.status_code}")
        return None

    data = r.json()
    ts = data.get("timestamp", [])
    if not ts:
        return None

    # assume single candle in response
    dt_utc = datetime.fromtimestamp(ts[0], tz=timezone.utc)
    dt_ist = dt_utc.astimezone(IST)

    # Dhan timestamp = candle CLOSE time
    # Convert to candle START time (−1 minute)
    dt_start = dt_ist - timedelta(minutes=1)

    return {
        "ts": fmt_ts(dt_start),
        "open": data["open"][0],
        "high": data["high"][0],
        "low": data["low"][0],
        "close": data["close"][0],
        "volume": 0,
    }


# ---------------- CORE ----------------
def run():
    """
    Fetch and append the last completed 1-minute candle safely.

    Guarantees:
        - strictly increasing timestamps
        - no duplicates
        - no future candles
        - resilient to API fallback behaviour
    """

    target = last_completed_minute()
    file_path = today_file()

    last_saved = read_last_timestamp(file_path)

    # --------------------------------------------------
    # Nothing new expected yet
    # --------------------------------------------------
    if last_saved and last_saved >= target:
        logger.info("SPOT_UPDATE: already up-to-date")
        return

    # --------------------------------------------------
    # Fetch candle from API
    # --------------------------------------------------
    candle = fetch_candle(target)

    if not candle:
        logger.info(f"Candle not yet available: {fmt_ts(target)}")
        return

    candle_dt = parse_ts(candle["ts"])

    # --------------------------------------------------
    # SAFETY 1 — reject future candles
    # (API sometimes returns latest available)
    # --------------------------------------------------
    # --------------------------------------------------
    # SAFETY 1 — enforce exact minute match
    # We store candles using START time convention:
    # interval = [ts, ts + 1 minute)
    # --------------------------------------------------
    if candle_dt != target:
        logger.info(
            f"Ignoring mismatched candle from API: {candle['ts']} "
            f"(expected={fmt_ts(target)})"
        )
        return

    # --------------------------------------------------
    # SAFETY 2 — reject duplicates or backward time
    # --------------------------------------------------
    if last_saved and candle_dt <= last_saved:
        logger.info(
            f"Ignoring duplicate/old candle: {candle['ts']} "
            f"(last_saved={fmt_ts(last_saved)})"
        )
        return

    # --------------------------------------------------
    # Append valid candle
    # --------------------------------------------------
    append_row(file_path, candle)

    logger.info(f"SPOT_UPDATE: appended {candle['ts']}")


if __name__ == "__main__":
    run()