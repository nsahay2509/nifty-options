# nifty_evaluator.py

import time
import sys
import subprocess
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from scripts.paper_trade_engine import run as run_paper_trade
from scripts.logger import get_logger
from scripts.paper_mtm_engine import run as run_mtm


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


def run_cycle():

    logger.info("")
    logger.info("-" * 60)
    logger.info("CYCLE START")
    logger.info("-" * 60)

    logger.info("STEP 1: updater start")
    ok = run_updater()
    logger.info(f"STEP 1: updater end | ok={ok}")

    if ok:
        logger.info("STEP 2: paper_trade start")
        run_paper_trade()
        logger.info("STEP 2: paper_trade end")

        logger.info("STEP 3: mtm start")
        run_mtm()
        logger.info("STEP 3: mtm end")

    logger.info("-" * 60)
    logger.info("CYCLE END")
    logger.info("-" * 60)
    logger.info("")


# ---------------- MAIN LOOP ----------------
def main():

    logger.info("NIFTY Evaluator Started")
    logger.info("Schedule: Mon–Fri | 09:15–15:30 IST | Every minute +2 sec")
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