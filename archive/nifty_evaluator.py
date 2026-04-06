# nifty_evaluator.py

import sys
from datetime import datetime, timedelta

from scripts.app_config import APP_CONFIG, IST
from scripts.clock import get_clock
from scripts.option_resolver import get_atm_straddle
from scripts.evaluator_service import (
    run_cycle,
    run_updater,
)
from scripts.evaluator_service import (
    collect_open_position_security_ids as service_collect_open_position_security_ids,
)
from scripts.evaluator_service import (
    collect_regime_security_ids as service_collect_regime_security_ids,
)
from scripts.logger import get_logger
CONFIG = APP_CONFIG.evaluator

logger = get_logger("evaluator")
_last_cycle_key = None

# ---------------- HELPERS ----------------
def is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5


def next_run_time(now: datetime) -> datetime:
    base = now.replace(second=0, microsecond=0)
    target = base.replace(second=CONFIG.run_delay_sec)

    if now < target:
        return target

    return (base + timedelta(minutes=1)).replace(second=CONFIG.run_delay_sec)


def sleep_until(target: datetime, clock=None):
    active_clock = clock or get_clock()
    seconds = (target - active_clock.now()).total_seconds()
    if seconds > 0:
        active_clock.sleep(seconds)


def collect_open_position_security_ids(position_file, label: str) -> list[int]:
    return service_collect_open_position_security_ids(position_file, label)


def collect_regime_security_ids(regime, history) -> list[int]:
    return service_collect_regime_security_ids(
        regime,
        history,
        resolver=get_atm_straddle,
    )


# ---------------- MAIN LOOP ----------------
def main():
    clock = get_clock()

    logger.info("NIFTY Evaluator Started")
    logger.info(
        f"Schedule: Mon–Fri | 09:15–15:30 IST | Every minute +{CONFIG.run_delay_sec} sec"
    )
    logger.info("-" * 60)

    while True:
        now = clock.now()

        # Weekend
        if not is_weekday(now):
            clock.sleep(60)
            continue

        # Before market
        if now.time() < CONFIG.start_time:
            target = now.replace(
                hour=CONFIG.start_time.hour,
                minute=CONFIG.start_time.minute,
                second=2,
                microsecond=0,
            )
            sleep_until(target, clock=clock)
            continue

        # After market
        if now.time() >= CONFIG.end_time:
            tomorrow = now + timedelta(days=1)
            target = tomorrow.replace(
                hour=CONFIG.start_time.hour,
                minute=CONFIG.start_time.minute,
                second=2,
                microsecond=0,
            )
            sleep_until(target, clock=clock)
            continue

        # During market
        run_at = next_run_time(now)
        sleep_until(run_at, clock=clock)

        try:
            run_cycle(clock=clock)
        except Exception as e:
            logger.exception(f"CYCLE ERROR: {e}")


if __name__ == "__main__":
    main()
