



# python -m tests.structure_scan

import json
from pathlib import Path
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from scripts.regime_classifier import classify_regime


# ---------------- CONFIG ----------------
IST = ZoneInfo("Asia/Kolkata")

DATA_DIR = Path("data/spot")

DATE = "2026-02-20"      # change date here
START_EVAL_TIME = dtime(9, 20)


# ---------------- HELPERS ----------------
def load_day(date_str: str):
    file_path = DATA_DIR / f"{date_str}.jsonl"

    if not file_path.exists():
        raise FileNotFoundError(file_path)

    candles = []

    with open(file_path) as f:
        for line in f:
            candles.append(json.loads(line))

    return candles


# ---------------- CORE ----------------
def run():

    candles = load_day(DATE)

    print()
    print(f"STRUCTURE SCAN TEST — {DATE}")
    print("-" * 60)

    history = []

    for candle in candles:

        ts = datetime.fromisoformat(candle["ts"]).replace(tzinfo=IST)
        history.append(candle)

        if ts.time() < START_EVAL_TIME:
            continue

        regime = classify_regime(history)

        print(f"{ts.strftime('%H:%M')}  ->  {regime}")


# ---------------- ENTRY ----------------
if __name__ == "__main__":
    run()