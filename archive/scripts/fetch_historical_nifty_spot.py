

# python -m scripts.fetch_historical_nifty_spot




import os
import json
import time
import tempfile
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from scripts.utils import get_dhan_headers


# ---------------- CONFIG ----------------
IST = ZoneInfo("Asia/Kolkata")

URL = "https://api.dhan.co/v2/charts/intraday"

SECURITY_ID = "13"
EXCHANGE_SEGMENT = "IDX_I"
INSTRUMENT = "INDEX"
INTERVAL = "1"

MARKET_START = "09:15:00"
MARKET_END   = "15:30:00"

MAX_RETRIES = 4
THROTTLE_SLEEP = 0.25

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(BASE_DIR, "data", "spot")
# OUTDIR = os.path.join(BASE_DIR, "data", "spot_test")
os.makedirs(OUTDIR, exist_ok=True)


# ---------------- HELPERS ----------------
def is_weekday(day: datetime) -> bool:
    return day.weekday() < 5


def _post(payload: dict):
    headers = get_dhan_headers()
    headers["Accept"] = "application/json"

    for _ in range(MAX_RETRIES):
        try:
            r = requests.post(URL, headers=headers, json=payload, timeout=10)
        except Exception:
            time.sleep(1)
            continue

        if r.status_code == 200:
            return r

        if r.status_code == 429:
            time.sleep(1.5)
            continue

        if r.status_code == 400:
            return None

        return None

    return None


def _atomic_write_jsonl(path: str, rows: list):
    dirpath = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".jsonl", dir=dirpath)

    try:
        with os.fdopen(fd, "w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ---------------- CORE ----------------
def fetch_day(day: datetime):

    day_str = day.strftime("%Y-%m-%d")
    fname = os.path.join(OUTDIR, f"{day_str}.jsonl")

    if os.path.exists(fname) and os.path.getsize(fname) > 0:
        print(f"{day_str}: ⏭ Skipped")
        return

    payload = {
        "securityId": SECURITY_ID,
        "exchangeSegment": EXCHANGE_SEGMENT,
        "instrument": INSTRUMENT,
        "interval": INTERVAL,
        "oi": False,
        "fromDate": f"{day_str} {MARKET_START}",
        "toDate":   f"{day_str} {MARKET_END}",
    }

    r = _post(payload)
    if not r:
        print(f"{day_str}: ⏭ Non-trading / no data")
        return

    data = r.json()
    ts = data.get("timestamp", [])

    if not ts:
        print(f"{day_str}: ⏭ Empty")
        return

    rows = []

    for i in range(len(ts)):

        # Correct conversion: UTC epoch → IST
        dt_utc = datetime.fromtimestamp(ts[i], tz=timezone.utc)
        dt_ist = dt_utc.astimezone(IST)

        # Strict session filter (safety)
        if not (dt_ist.hour > 9 or (dt_ist.hour == 9 and dt_ist.minute >= 15)):
            continue
        if not (dt_ist.hour < 15 or (dt_ist.hour == 15 and dt_ist.minute <= 30)):
            continue

        rows.append({
            "ts": dt_ist.strftime("%Y-%m-%d %H:%M:%S"),
            "open": data["open"][i],
            "high": data["high"][i],
            "low": data["low"][i],
            "close": data["close"][i],
            "volume": 0   # Spot index has no tradable volume
        })

    if not rows:
        print(f"{day_str}: ⏭ No valid session candles")
        return

    _atomic_write_jsonl(fname, rows)

    print(f"{day_str}: ✔ Saved {len(rows)} rows")


def run():
    print("\n==============================")
    print("  FETCHING NIFTY SPOT (1-min)")
    print("==============================\n")

    start = datetime(2026, 1, 1)
    end   = datetime(2026, 2, 18)

    # start = datetime(2026, 2, 27)
    # end   = datetime(2026, 2, 27)

    day = start
    while day <= end:
        if is_weekday(day):
            fetch_day(day)
            time.sleep(THROTTLE_SLEEP)
        day += timedelta(days=1)


if __name__ == "__main__":
    run()