# nifty_evaluator.py

import time
import json
import sys
import subprocess
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from scripts.paper_trade_engine import run as run_paper_trade
from scripts.logger import get_logger
from scripts.paper_mtm_engine import run as run_mtm
from scripts.paper_trade_engine_buy import run as run_buy_trade
from scripts.paper_mtm_engine_buy import run as run_buy_mtm
from scripts.regime_classifier import load_last_candles
from scripts.signal_engine import generate_signal
from scripts.utils import ensure_complete_ltp_map
from scripts.option_resolver import get_atm_straddle
from scripts.state_utils import safe_load_json

# ---------------- CONFIG ----------------
IST = ZoneInfo("Asia/Kolkata")

START_TIME = dtime(9, 15)
END_TIME   = dtime(15, 30)
RUN_DELAY_SEC = 5

BASE_DIR = Path(__file__).resolve().parent

logger = get_logger("evaluator")
_last_cycle_key = None

# ---------------- HELPERS ----------------
def is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5


def next_run_time(now: datetime) -> datetime:
    base = now.replace(second=0, microsecond=0)
    target = base.replace(second=RUN_DELAY_SEC)

    if now < target:
        return target

    return (base + timedelta(minutes=1)).replace(second=RUN_DELAY_SEC)


def sleep_until(target: datetime):
    seconds = (target - datetime.now(IST)).total_seconds()
    if seconds > 0:
        time.sleep(seconds)


def run_updater():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.update_nifty_spot"],
            cwd=BASE_DIR,
        )

        if result.returncode != 0:
            logger.error("UPDATE FAILED")
            return False

        return True

    except Exception as e:
        logger.exception(f"Updater crashed: {e}")
        return False


def collect_open_position_security_ids(position_file: Path, label: str) -> list[int]:
    position = safe_load_json(position_file, None)
    if not position:
        return []

    if position.get("status") != "OPEN":
        return []

    security_ids = []

    for leg in position.get("legs", []):
        raw_sid = leg.get("security_id")
        try:
            sid = int(raw_sid)
        except (TypeError, ValueError):
            logger.warning(
                f"{label}_POSITION_INVALID_SECURITY_ID | file={position_file.name} leg={leg}"
            )
            continue

        security_ids.append(sid)

    return security_ids


def collect_regime_security_ids(regime, history) -> list[int]:
    if regime not in ("SELL_PE", "SELL_CE"):
        return []

    if not history:
        logger.warning("REGIME_SECURITY_COLLECTION_SKIPPED | history_empty")
        return []

    try:
        spot = history[-1]["close"]
        atm = get_atm_straddle(spot)
    except Exception as exc:
        logger.exception(f"REGIME_SECURITY_COLLECTION_FAILED | regime={regime} error={exc}")
        return []

    if regime == "SELL_PE":
        return [atm["pe_security_id"], atm["ce_security_id"]]

    return [atm["ce_security_id"], atm["pe_security_id"]]


def run_cycle():

    logger.info("")
    logger.info("-" * 60)
    logger.info("CYCLE START")
    logger.info("-" * 60)

    logger.info("STEP 1: updater start")
    ok = run_updater()
    logger.info(f"STEP 1: updater end | ok={ok}")

    if ok:
        # ---- generate signal once ----
        history = load_last_candles(25)
        signal, regime = generate_signal(history)

        logger.info(f"MASTER_SIGNAL | signal={signal} regime={regime}")

        # ==================================================
        # ⭐ STEP 2: COLLECT SECURITY IDS (for shared LTP)
        # ==================================================
        security_ids = []

        sell_file = BASE_DIR / "data" / "open_position.json"
        security_ids.extend(collect_open_position_security_ids(sell_file, "SELL"))

        buy_file = BASE_DIR / "data" / "open_position_buy.json"
        security_ids.extend(collect_open_position_security_ids(buy_file, "BUY"))

        security_ids.extend(collect_regime_security_ids(regime, history))

        # remove duplicates
        security_ids = list(set(security_ids))


        # ==================================================
        # ⭐ STEP 3: FETCH LTP ONCE
        # ==================================================
        ltp_map = {}
        if security_ids:
            ltp_map, complete = ensure_complete_ltp_map(
                security_ids,
                logger=logger,
            )
            if not complete:
                logger.warning(f"EVALUATOR_LTP_INCOMPLETE | ids={security_ids} map={ltp_map}")

        logger.info(f"LTP_MAP_CYCLE | {ltp_map}")

        # ==================================================
        # STEP 4: SELL side
        # ==================================================
        logger.info("STEP 2: SELL paper_trade start")
        run_paper_trade(
            signal=signal,
            regime=regime,
            history=history,
            ltp_map=ltp_map,
        )
        logger.info("STEP 2: SELL paper_trade end")

        logger.info("STEP 3: SELL mtm start")
        run_mtm(ltp_map=ltp_map)
        logger.info("STEP 3: SELL mtm end")

        # ==================================================
        # STEP 5: BUY side
        # ==================================================
        logger.info("STEP 4: BUY paper_trade start")
        run_buy_trade(
            signal=signal,
            regime=regime,
            history=history,
            ltp_map=ltp_map,
        )
        logger.info("STEP 4: BUY paper_trade end")

        logger.info("STEP 5: BUY mtm start")
        run_buy_mtm(ltp_map=ltp_map)
        logger.info("STEP 5: BUY mtm end")

    logger.info("-" * 60)
    logger.info("CYCLE END")
    logger.info("-" * 60)
    logger.info("")


# ---------------- MAIN LOOP ----------------
def main():

    logger.info("NIFTY Evaluator Started")
    logger.info(f"Schedule: Mon–Fri | 09:15–15:30 IST | Every minute +{RUN_DELAY_SEC} sec")
    logger.info("-" * 60)

    while True:
        now = datetime.now(IST)

        # Weekend
        if not is_weekday(now):
            time.sleep(60)
            continue

        # Before market
        if now.time() < START_TIME:
            target = now.replace(
                hour=START_TIME.hour,
                minute=START_TIME.minute,
                second=2,
                microsecond=0,
            )
            sleep_until(target)
            continue

        # After market
        if now.time() >= END_TIME:
            tomorrow = now + timedelta(days=1)
            target = tomorrow.replace(
                hour=START_TIME.hour,
                minute=START_TIME.minute,
                second=2,
                microsecond=0,
            )
            sleep_until(target)
            continue

        # During market
        run_at = next_run_time(now)
        sleep_until(run_at)

        try:
            run_cycle()
        except Exception as e:
            logger.exception(f"CYCLE ERROR: {e}")


if __name__ == "__main__":
    main()
