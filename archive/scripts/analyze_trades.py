import csv
import math
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from statistics import median

from scripts.app_config import APP_CONFIG
from scripts.logger import get_logger
from scripts.models import DailySummaryRow, TradeEventRow, TradeSummaryRow

# ---------- paths ----------
BASE_DIR = Path(__file__).resolve().parents[1]

RESULT_DIR = BASE_DIR / "data" / "results"
ENGINE_LOG_FILE = BASE_DIR / "data" / "logs" / "nifty_engine.log"

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
PERFORMANCE_SUMMARY_FILE = RESULT_DIR / "performance_summary.csv"
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
    "exit_spot",
    "exit_direction_score",
    "exit_bias",
    "peak_pnl",
    "drawdown_from_peak",
    "cooldown_applied_min",
    "diagnostic_context",
]

DHAN_BROKERAGE_PER_ORDER = 20.0
NSE_OPTIONS_TRANSACTION_RATE = 0.0003503
SEBI_TURNOVER_RATE = 0.000001
OPTIONS_STAMP_DUTY_BUY_RATE = 0.00003
GST_RATE = 0.18
OPTIONS_STT_SELL_RATE = 0.001

ENTRY_LOG_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| "
    r"(?P<engine>paper_trade(?:_buy)?) \| LTP_MAP_ENTRY \| "
    r"ids=\[(?P<ids>[^\]]*)\] map=\{(?P<price_map>.*)\}$"
)

PERFORMANCE_SUMMARY_FIELDS = [
    "side",
    "date_from",
    "date_to",
    "trading_days",
    "total_trades",
    "winning_trades",
    "losing_trades",
    "flat_trades",
    "win_rate_pct",
    "gross_pnl",
    "gross_profit",
    "gross_loss",
    "estimated_cost",
    "net_after_cost",
    "avg_trade_pnl",
    "median_trade_pnl",
    "profit_factor",
    "best_trade",
    "worst_trade",
    "avg_day_pnl",
    "best_day",
    "worst_day",
    "max_drawdown",
    "max_loss_streak",
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

        estimated_cost = sum(
            float(t.get("estimated_cost", APP_CONFIG.reporting.trade_cost))
            for t in trade_list
        )
        net_pnl = gross_pnl - estimated_cost

        existing_rows[date] = DailySummaryRow(
            date=date,
            total_trades=total_trades,
            winning_trades=winning,
            losing_trades=losing,
            gross_pnl=round(gross_pnl, 2),
            estimated_cost=round(estimated_cost, 2),
            net_pnl=round(net_pnl, 2),
        ).to_dict()

    rows = [row for _, row in sorted(existing_rows.items())]
    write_csv_rows(daily_summary_file, DAILY_SUMMARY_FIELDS, rows)


def run_analysis(system_pnl_file, trade_summary_file, daily_summary_file):
    trades = extract_trades(system_pnl_file)
    update_trade_summary(trades, trade_summary_file)
    update_daily_summary(trades, daily_summary_file)
    return trades


def extract_trades_from_events(source_file):
    if not Path(source_file).exists():
        return []

    with open(source_file) as f:
        rows = [TradeEventRow.from_dict(row) for row in csv.DictReader(f)]
    rows = enrich_event_rows_with_prices(rows)

    return [
        {
            **TradeSummaryRow(
                trade_id=row.trade_id,
                entry_time=row.entry_time,
                exit_time=row.exit_time,
                time_in_trade_min=row.time_in_trade_min,
                trade_type=row.regime,
                strike=str(row.strike),
                expiry=row.expiry,
                trade_pnl=round(row.trade_pnl, 2),
            ).to_dict(),
            "estimated_cost": round(estimate_trade_cost_from_event(row), 2),
        }
        for row in rows
    ]


def round_rupee(value: float) -> float:
    return float(int(math.floor(value + 0.5)))


def load_logged_entry_prices() -> dict[tuple[str, str], float]:
    if not ENGINE_LOG_FILE.exists():
        return {}

    price_map = {}
    with open(ENGINE_LOG_FILE) as f:
        for line in f:
            match = ENTRY_LOG_PATTERN.match(line.strip())
            if not match:
                continue

            timestamp = match.group("timestamp")
            side = "BUY" if match.group("engine") == "paper_trade_buy" else "SELL"
            ids = [item.strip() for item in match.group("ids").split(",") if item.strip()]
            if not ids:
                continue

            selected_id = ids[0]
            raw_prices = {}
            for part in match.group("price_map").split(","):
                if ":" not in part:
                    continue
                key, value = part.split(":", 1)
                raw_prices[key.strip()] = float(value.strip())

            if selected_id in raw_prices:
                price_map[(side, timestamp)] = raw_prices[selected_id]

    return price_map


def enrich_event_rows_with_prices(rows: list[TradeEventRow]) -> list[TradeEventRow]:
    logged_entry_prices = load_logged_entry_prices()
    enriched = []

    for row in rows:
        quantity = int(row.quantity or 0) or (APP_CONFIG.trade.lot_size * APP_CONFIG.trade.lots)
        entry_price = float(row.entry_price or 0.0)
        exit_price = float(row.exit_price or 0.0)

        if entry_price <= 0:
            entry_price = float(logged_entry_prices.get((row.side, row.entry_time), 0.0))

        if exit_price <= 0 and entry_price > 0 and quantity > 0:
            if row.side == "BUY":
                exit_price = entry_price + (row.trade_pnl / quantity)
            elif row.side == "SELL":
                exit_price = entry_price - (row.trade_pnl / quantity)

        enriched.append(TradeEventRow(
            side=row.side,
            trade_id=row.trade_id,
            regime=row.regime,
            entry_signal=row.entry_signal,
            entry_time=row.entry_time,
            exit_time=row.exit_time,
            time_in_trade_min=row.time_in_trade_min,
            strike=row.strike,
            expiry=row.expiry,
            entry_spot=row.entry_spot,
            entry_direction_score=row.entry_direction_score,
            entry_bias=row.entry_bias,
            exit_reason=row.exit_reason,
            trade_pnl=row.trade_pnl,
            entry_price=round(entry_price, 2) if entry_price > 0 else 0.0,
            exit_price=round(exit_price, 2) if exit_price > 0 else 0.0,
            quantity=quantity,
            exit_spot=row.exit_spot,
            exit_direction_score=row.exit_direction_score,
            exit_bias=row.exit_bias,
            peak_pnl=row.peak_pnl,
            drawdown_from_peak=row.drawdown_from_peak,
            cooldown_applied_min=row.cooldown_applied_min,
            diagnostic_context=row.diagnostic_context,
        ))

    return enriched


def estimate_trade_cost_from_event(row: TradeEventRow) -> float:
    quantity = int(row.quantity or 0)
    entry_price = float(row.entry_price or 0.0)
    exit_price = float(row.exit_price or 0.0)
    side = (row.side or "").upper()

    if quantity <= 0 or entry_price <= 0 or exit_price <= 0 or side not in {"BUY", "SELL"}:
        return float(APP_CONFIG.reporting.trade_cost)

    if side == "BUY":
        buy_value = entry_price * quantity
        sell_value = exit_price * quantity
    else:
        buy_value = exit_price * quantity
        sell_value = entry_price * quantity

    turnover = buy_value + sell_value
    brokerage = DHAN_BROKERAGE_PER_ORDER * 2
    transaction_charge = turnover * NSE_OPTIONS_TRANSACTION_RATE
    sebi_charge = turnover * SEBI_TURNOVER_RATE
    stamp_duty = round_rupee(buy_value * OPTIONS_STAMP_DUTY_BUY_RATE)
    stt = round_rupee(sell_value * OPTIONS_STT_SELL_RATE)
    gst = round(brokerage + transaction_charge + sebi_charge, 2) * GST_RATE

    return round(
        brokerage
        + round(transaction_charge, 2)
        + round(sebi_charge, 2)
        + stamp_duty
        + stt
        + round(gst, 2),
        2,
    )


def export_trade_quality_summary(source_file, target_file):
    if not Path(source_file).exists():
        write_csv_rows(target_file, TRADE_QUALITY_FIELDS, [])
        return []

    with open(source_file) as f:
        rows = list(csv.DictReader(f))

    write_csv_rows(target_file, TRADE_QUALITY_FIELDS, rows)

    return rows


def run_reporting_spec(spec: dict):
    if APP_CONFIG.reporting.prefer_trade_events:
        trades = extract_trades_from_events(spec["trade_events"])
        update_trade_summary(trades, spec["trade_summary"])
        update_daily_summary(trades, spec["daily_summary"])
    else:
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


def build_performance_summary_row(side: str, trades: list[dict]):
    ordered_trades = sorted(
        trades,
        key=lambda trade: (trade["exit_time"], trade["trade_id"]),
    )

    if not ordered_trades:
        return {
            "side": side,
            "date_from": "",
            "date_to": "",
            "trading_days": 0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "flat_trades": 0,
            "win_rate_pct": 0.0,
            "gross_pnl": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "estimated_cost": 0,
            "net_after_cost": 0.0,
            "avg_trade_pnl": 0.0,
            "median_trade_pnl": 0.0,
            "profit_factor": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "avg_day_pnl": 0.0,
            "best_day": 0.0,
            "worst_day": 0.0,
            "max_drawdown": 0.0,
            "max_loss_streak": 0,
        }

    pnls = [float(trade["trade_pnl"]) for trade in ordered_trades]
    trade_dates = [trade["entry_time"].split(" ")[0] for trade in ordered_trades]

    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
    gross_pnl = sum(pnls)
    total_trades = len(pnls)
    winning_trades = sum(1 for pnl in pnls if pnl > 0)
    losing_trades = sum(1 for pnl in pnls if pnl < 0)
    flat_trades = total_trades - winning_trades - losing_trades
    estimated_cost = sum(
        float(trade.get("estimated_cost", APP_CONFIG.reporting.trade_cost))
        for trade in ordered_trades
    )
    net_after_cost = gross_pnl - estimated_cost

    daily_pnl = defaultdict(float)
    for trade in ordered_trades:
        daily_pnl[trade["entry_time"].split(" ")[0]] += float(trade["trade_pnl"])

    equity = 0.0
    equity_peak = 0.0
    max_drawdown = 0.0
    max_loss_streak = 0
    current_loss_streak = 0
    for pnl in pnls:
        equity += pnl
        equity_peak = max(equity_peak, equity)
        max_drawdown = min(max_drawdown, equity - equity_peak)
        if pnl < 0:
            current_loss_streak += 1
            max_loss_streak = max(max_loss_streak, current_loss_streak)
        else:
            current_loss_streak = 0

    return {
        "side": side,
        "date_from": min(trade_dates),
        "date_to": max(trade_dates),
        "trading_days": len(daily_pnl),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "flat_trades": flat_trades,
        "win_rate_pct": round((winning_trades / total_trades) * 100, 2),
        "gross_pnl": round(gross_pnl, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "estimated_cost": estimated_cost,
        "net_after_cost": round(net_after_cost, 2),
        "avg_trade_pnl": round(gross_pnl / total_trades, 2),
        "median_trade_pnl": round(median(pnls), 2),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else 0.0,
        "best_trade": round(max(pnls), 2),
        "worst_trade": round(min(pnls), 2),
        "avg_day_pnl": round(gross_pnl / len(daily_pnl), 2),
        "best_day": round(max(daily_pnl.values()), 2),
        "worst_day": round(min(daily_pnl.values()), 2),
        "max_drawdown": round(max_drawdown, 2),
        "max_loss_streak": max_loss_streak,
    }


def export_performance_summary(rows: list[dict]):
    write_csv_rows(PERFORMANCE_SUMMARY_FILE, PERFORMANCE_SUMMARY_FIELDS, rows)
    logger.info(f"Performance summary updated: {PERFORMANCE_SUMMARY_FILE}")


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
    export_performance_summary([
        build_performance_summary_row("sell", sell_trades),
        build_performance_summary_row("buy", buy_trades),
        build_performance_summary_row("combined", combined_trades),
    ])


if __name__ == "__main__":
    main()
