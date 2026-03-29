import csv
import math
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from scripts.app_config import APP_CONFIG
from scripts.logger import get_logger
from scripts.models import DailySummaryRow, TradeSummaryRow

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
logger = get_logger("analyze_trades")

TRADE_SUMMARY_FIELDS = [
    "trade_id",
    "entry_time",
    "exit_time",
    "time_in_trade_min",
    "trade_type",
    "strike",
    "expiry",
    "trade_pnl",
]

DAILY_SUMMARY_FIELDS = [
    "date",
    "total_trades",
    "winning_trades",
    "losing_trades",
    "gross_pnl",
    "estimated_cost",
    "net_pnl",
]

TRADE_QUALITY_FIELDS = [
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

REPORT_SPECS = {
    "sell": {
        "label": "Sell",
        "system_pnl": SYSTEM_PNL_FILE,
        "trade_summary": TRADE_SUMMARY_FILE,
        "daily_summary": DAILY_SUMMARY_FILE,
        "trade_events": TRADE_EVENTS_SELL_FILE,
        "trade_quality": TRADE_QUALITY_FILE,
    },
    "buy": {
        "label": "Buy",
        "system_pnl": SYSTEM_PNL_BUY_FILE,
        "trade_summary": TRADE_SUMMARY_BUY_FILE,
        "daily_summary": DAILY_SUMMARY_BUY_FILE,
        "trade_events": TRADE_EVENTS_BUY_FILE,
        "trade_quality": TRADE_QUALITY_BUY_FILE,
    },
}

def parse_time(ts):
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict]):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


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

                trades.append(TradeSummaryRow(
                    trade_id=current_trade["trade_id"],
                    entry_time=current_trade["entry_time"],
                    exit_time=timestamp,
                    time_in_trade_min=duration,
                    trade_type=current_trade["trade_type"],
                    strike=current_trade["strike"],
                    expiry=current_trade["expiry"],
                    trade_pnl=round(trade_pnl, 2),
                ).to_dict())

                current_trade = None

    return trades


# ------------------------------------------------
# UPDATE TRADE SUMMARY
# ------------------------------------------------

def update_trade_summary(trades, trade_summary_file):
    rows = [
        dict(t)
        for t in sorted(trades, key=lambda trade: (trade["entry_time"], trade["trade_id"]))
    ]
    write_csv_rows(trade_summary_file, TRADE_SUMMARY_FIELDS, rows)


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

        estimated_cost = total_trades * APP_CONFIG.reporting.trade_cost
        net_pnl = gross_pnl - estimated_cost

        existing_rows[date] = DailySummaryRow(
            date=date,
            total_trades=total_trades,
            winning_trades=winning,
            losing_trades=losing,
            gross_pnl=round(gross_pnl, 2),
            estimated_cost=estimated_cost,
            net_pnl=round(net_pnl, 2),
        ).to_dict()

    rows = [row for _, row in sorted(existing_rows.items())]
    write_csv_rows(daily_summary_file, DAILY_SUMMARY_FIELDS, rows)


def run_analysis(system_pnl_file, trade_summary_file, daily_summary_file):
    trades = extract_trades(system_pnl_file)
    update_trade_summary(trades, trade_summary_file)
    update_daily_summary(trades, daily_summary_file)
    return trades


def export_trade_quality_summary(source_file, target_file):
    if not Path(source_file).exists():
        write_csv_rows(target_file, TRADE_QUALITY_FIELDS, [])
        return []

    with open(source_file) as f:
        rows = list(csv.DictReader(f))

    write_csv_rows(target_file, TRADE_QUALITY_FIELDS, rows)

    return rows


def run_reporting_spec(spec: dict):
    trades = run_analysis(
        spec["system_pnl"],
        spec["trade_summary"],
        spec["daily_summary"],
    )
    logger.info(f"{spec['label']} trade summary updated: {spec['trade_summary']}")
    logger.info(f"{spec['label']} daily summary updated: {spec['daily_summary']}")

    quality_rows = export_trade_quality_summary(
        spec["trade_events"],
        spec["trade_quality"],
    )
    logger.info(f"{spec['label']} trade quality summary updated: {spec['trade_quality']}")
    return trades, quality_rows


def export_combined_outputs(combined_trades, combined_quality):
    update_trade_summary(combined_trades, TRADE_SUMMARY_COMBINED_FILE)
    update_daily_summary(combined_trades, DAILY_SUMMARY_COMBINED_FILE)
    logger.info(f"Combined trade summary updated: {TRADE_SUMMARY_COMBINED_FILE}")
    logger.info(f"Combined daily summary updated: {DAILY_SUMMARY_COMBINED_FILE}")

    write_csv_rows(TRADE_QUALITY_COMBINED_FILE, TRADE_QUALITY_FIELDS, combined_quality)
    logger.info(f"Combined trade quality summary updated: {TRADE_QUALITY_COMBINED_FILE}")


# ------------------------------------------------
# MAIN
# ------------------------------------------------

def main():
    sell_trades, sell_quality = run_reporting_spec(REPORT_SPECS["sell"])
    buy_trades, buy_quality = run_reporting_spec(REPORT_SPECS["buy"])

    combined_trades = sorted(
        sell_trades + buy_trades,
        key=lambda trade: (trade["entry_time"], trade["trade_id"]),
    )
    combined_quality = sorted(
        sell_quality + buy_quality,
        key=lambda row: (row.get("entry_time", ""), row.get("trade_id", ""), row.get("side", "")),
    )
    export_combined_outputs(combined_trades, combined_quality)


if __name__ == "__main__":
    main()
