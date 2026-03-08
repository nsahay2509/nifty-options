




# python3 scripts/analyze_trades.py



# python3 scripts/analyze_trades.py

import csv
import math
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ---------- paths ----------
BASE_DIR = Path(__file__).resolve().parents[1]

RESULT_DIR = BASE_DIR / "data" / "results"

SYSTEM_PNL_FILE = RESULT_DIR / "system_pnl.csv"
TRADE_SUMMARY_FILE = RESULT_DIR / "trade_summary.csv"
DAILY_SUMMARY_FILE = RESULT_DIR / "daily_summary.csv"

# approx cost per trade
TRADE_COST = 100


def parse_time(ts):
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


# ------------------------------------------------
# PARSE SYSTEM PNL
# ------------------------------------------------

def extract_trades():

    trades = []
    current_trade = None

    with open(SYSTEM_PNL_FILE) as f:

        reader = csv.reader(f)
        next(reader, None)  # skip header

        for row in reader:

            if len(row) < 7:
                continue

            timestamp, trade_id, event, trade_type, strike, expiry = row[:6]

            try:
                realised = float(row[6])
            except ValueError:
                continue

            if event == "ENTRY":

                current_trade = {
                    "trade_id": trade_id,
                    "entry_time": timestamp,
                    "trade_type": trade_type,
                    "strike": strike,
                    "expiry": expiry,
                    "entry_realised": realised,
                }

            elif event == "EXIT" and current_trade:

                entry_time = parse_time(current_trade["entry_time"])
                exit_time = parse_time(timestamp)

                duration = (exit_time - entry_time).total_seconds() / 60
                duration = math.ceil(duration)

                trade_pnl = realised - current_trade["entry_realised"]

                trades.append({
                    "trade_id": current_trade["trade_id"],
                    "entry_time": current_trade["entry_time"],
                    "exit_time": timestamp,
                    "time_in_trade_min": duration,
                    "trade_type": current_trade["trade_type"],
                    "strike": current_trade["strike"],
                    "expiry": current_trade["expiry"],
                    "trade_pnl": round(trade_pnl, 2),
                })

                current_trade = None

    return trades


# ------------------------------------------------
# UPDATE TRADE SUMMARY
# ------------------------------------------------

def update_trade_summary(trades):

    existing_ids = set()

    if TRADE_SUMMARY_FILE.exists():

        with open(TRADE_SUMMARY_FILE) as f:
            reader = csv.reader(f)
            next(reader, None)

            for row in reader:
                if row:
                    existing_ids.add(row[0])

    write_header = not TRADE_SUMMARY_FILE.exists()

    with open(TRADE_SUMMARY_FILE, "a", newline="") as f:

        writer = csv.writer(f)

        if write_header:
            writer.writerow([
                "trade_id",
                "entry_time",
                "exit_time",
                "time_in_trade_min",
                "trade_type",
                "strike",
                "expiry",
                "trade_pnl",
            ])

        for t in trades:

            if t["trade_id"] in existing_ids:
                continue

            writer.writerow([
                t["trade_id"],
                t["entry_time"],
                t["exit_time"],
                t["time_in_trade_min"],
                t["trade_type"],
                t["strike"],
                t["expiry"],
                t["trade_pnl"],
            ])


# ------------------------------------------------
# UPDATE DAILY SUMMARY
# ------------------------------------------------

def update_daily_summary(trades):

    daily = defaultdict(list)

    for t in trades:
        date = t["entry_time"].split(" ")[0]
        daily[date].append(t)

    existing_rows = {}

    if DAILY_SUMMARY_FILE.exists():

        with open(DAILY_SUMMARY_FILE) as f:
            reader = csv.reader(f)
            next(reader, None)

            for row in reader:
                if row:
                    existing_rows[row[0]] = row

    for date, trade_list in daily.items():

        total_trades = len(trade_list)
        winning = sum(1 for t in trade_list if t["trade_pnl"] > 0)
        losing = sum(1 for t in trade_list if t["trade_pnl"] <= 0)

        gross_pnl = sum(t["trade_pnl"] for t in trade_list)

        estimated_cost = total_trades * TRADE_COST
        net_pnl = gross_pnl - estimated_cost

        existing_rows[date] = [
            date,
            total_trades,
            winning,
            losing,
            round(gross_pnl, 2),
            estimated_cost,
            round(net_pnl, 2),
        ]

    with open(DAILY_SUMMARY_FILE, "w", newline="") as f:

        writer = csv.writer(f)

        writer.writerow([
            "date",
            "total_trades",
            "winning_trades",
            "losing_trades",
            "gross_pnl",
            "estimated_cost",
            "net_pnl",
        ])

        for row in sorted(existing_rows.values()):
            writer.writerow(row)


# ------------------------------------------------
# MAIN
# ------------------------------------------------

def main():

    trades = extract_trades()

    update_trade_summary(trades)
    update_daily_summary(trades)

    print("Trade summary updated:", TRADE_SUMMARY_FILE)
    print("Daily summary updated:", DAILY_SUMMARY_FILE)


if __name__ == "__main__":
    main()