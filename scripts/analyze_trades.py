




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
SYSTEM_PNL_BUY_FILE = RESULT_DIR / "system_pnl_buy.csv"
TRADE_SUMMARY_BUY_FILE = RESULT_DIR / "trade_summary_buy.csv"
DAILY_SUMMARY_BUY_FILE = RESULT_DIR / "daily_summary_buy.csv"
TRADE_SUMMARY_COMBINED_FILE = RESULT_DIR / "trade_summary_combined.csv"
DAILY_SUMMARY_COMBINED_FILE = RESULT_DIR / "daily_summary_combined.csv"
TRADE_EVENTS_SELL_FILE = RESULT_DIR / "trade_events_sell.csv"
TRADE_EVENTS_BUY_FILE = RESULT_DIR / "trade_events_buy.csv"
TRADE_QUALITY_FILE = RESULT_DIR / "trade_quality_summary.csv"
TRADE_QUALITY_BUY_FILE = RESULT_DIR / "trade_quality_summary_buy.csv"
TRADE_QUALITY_COMBINED_FILE = RESULT_DIR / "trade_quality_summary_combined.csv"

# approx cost per trade
TRADE_COST = 100


def parse_time(ts):
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


# ------------------------------------------------
# PARSE SYSTEM PNL
# ------------------------------------------------

def extract_trades(system_pnl_file):

    trades = []
    current_trade = None

    if not Path(system_pnl_file).exists():
        return trades

    with open(system_pnl_file) as f:

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

def update_trade_summary(trades, trade_summary_file):
    with open(trade_summary_file, "w", newline="") as f:
        writer = csv.writer(f)
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

        for t in sorted(trades, key=lambda trade: (trade["entry_time"], trade["trade_id"])):
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

def update_daily_summary(trades, daily_summary_file):

    daily = defaultdict(list)

    for t in trades:
        date = t["entry_time"].split(" ")[0]
        daily[date].append(t)

    existing_rows = {}

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

    with open(daily_summary_file, "w", newline="") as f:

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


def run_analysis(system_pnl_file, trade_summary_file, daily_summary_file):
    trades = extract_trades(system_pnl_file)
    update_trade_summary(trades, trade_summary_file)
    update_daily_summary(trades, daily_summary_file)
    return trades


def export_trade_quality_summary(source_file, target_file):
    if not Path(source_file).exists():
        with open(target_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "side",
                "trade_id",
                "regime",
                "entry_signal",
                "entry_time",
                "exit_time",
                "time_in_trade_min",
                "strike",
                "expiry",
                "entry_spot",
                "entry_direction_score",
                "entry_bias",
                "exit_reason",
                "trade_pnl",
            ])
        return []

    with open(source_file) as f:
        rows = list(csv.DictReader(f))

    with open(target_file, "w", newline="") as f:
        fieldnames = [
            "side",
            "trade_id",
            "regime",
            "entry_signal",
            "entry_time",
            "exit_time",
            "time_in_trade_min",
            "strike",
            "expiry",
            "entry_spot",
            "entry_direction_score",
            "entry_bias",
            "exit_reason",
            "trade_pnl",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})

    return rows


# ------------------------------------------------
# MAIN
# ------------------------------------------------

def main():
    sell_trades = run_analysis(
        SYSTEM_PNL_FILE,
        TRADE_SUMMARY_FILE,
        DAILY_SUMMARY_FILE,
    )
    print("Sell trade summary updated:", TRADE_SUMMARY_FILE)
    print("Sell daily summary updated:", DAILY_SUMMARY_FILE)

    buy_trades = run_analysis(
        SYSTEM_PNL_BUY_FILE,
        TRADE_SUMMARY_BUY_FILE,
        DAILY_SUMMARY_BUY_FILE,
    )
    print("Buy trade summary updated:", TRADE_SUMMARY_BUY_FILE)
    print("Buy daily summary updated:", DAILY_SUMMARY_BUY_FILE)

    combined_trades = sorted(
        sell_trades + buy_trades,
        key=lambda trade: (trade["entry_time"], trade["trade_id"]),
    )
    update_trade_summary(combined_trades, TRADE_SUMMARY_COMBINED_FILE)
    update_daily_summary(combined_trades, DAILY_SUMMARY_COMBINED_FILE)
    print("Combined trade summary updated:", TRADE_SUMMARY_COMBINED_FILE)
    print("Combined daily summary updated:", DAILY_SUMMARY_COMBINED_FILE)

    sell_quality = export_trade_quality_summary(
        TRADE_EVENTS_SELL_FILE,
        TRADE_QUALITY_FILE,
    )
    print("Sell trade quality summary updated:", TRADE_QUALITY_FILE)

    buy_quality = export_trade_quality_summary(
        TRADE_EVENTS_BUY_FILE,
        TRADE_QUALITY_BUY_FILE,
    )
    print("Buy trade quality summary updated:", TRADE_QUALITY_BUY_FILE)

    combined_quality = sorted(
        sell_quality + buy_quality,
        key=lambda row: (row.get("entry_time", ""), row.get("trade_id", ""), row.get("side", "")),
    )
    with open(TRADE_QUALITY_COMBINED_FILE, "w", newline="") as f:
        fieldnames = [
            "side",
            "trade_id",
            "regime",
            "entry_signal",
            "entry_time",
            "exit_time",
            "time_in_trade_min",
            "strike",
            "expiry",
            "entry_spot",
            "entry_direction_score",
            "entry_bias",
            "exit_reason",
            "trade_pnl",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in combined_quality:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    print("Combined trade quality summary updated:", TRADE_QUALITY_COMBINED_FILE)


if __name__ == "__main__":
    main()
