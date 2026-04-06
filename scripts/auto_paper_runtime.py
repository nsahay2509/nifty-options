"""Persistent supervisor that auto-starts paper evaluation on valid NSE trading days."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.config import APP_CONFIG
from scripts.log import configure_logging, get_logger
from scripts.market_calendar import MarketCalendar
from scripts.run_paper_live_eval import main as run_paper_live_eval_main
from scripts.runtime_controller import RuntimeAction, RuntimeController

logger = get_logger("auto_paper_runtime")


def compute_sleep_seconds(
    next_check_at: datetime,
    now: datetime,
    *,
    max_sleep_seconds: float = 300.0,
    min_sleep_seconds: float = 1.0,
) -> float:
    """Return the bounded idle wait before the next runtime evaluation."""
    remaining = max((next_check_at - now).total_seconds(), min_sleep_seconds)
    return min(remaining, max_sleep_seconds)


async def _sleep_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return


async def supervise_forever(
    *,
    runner: Callable[[], Awaitable[None]] = run_paper_live_eval_main,
    calendar: MarketCalendar | None = None,
    idle_max_seconds: float = 300.0,
    restart_delay_seconds: float = 5.0,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Keep the paper evaluator aligned to trading days and market hours."""
    calendar = calendar or MarketCalendar()
    controller = RuntimeController(calendar=calendar)
    stop_event = stop_event or asyncio.Event()
    idle_max_seconds = float(os.getenv("PAPER_AUTO_IDLE_MAX_SECONDS", str(idle_max_seconds)))
    restart_delay_seconds = float(os.getenv("PAPER_AUTO_RESTART_DELAY_SECONDS", str(restart_delay_seconds)))

    def request_stop(reason: str) -> None:
        if stop_event is None or stop_event.is_set():
            return
        logger.info("AUTO_RUNTIME_STOP_REQUESTED | reason=%s", reason)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig, reason in ((signal.SIGTERM, "manual_stop"), (signal.SIGINT, "keyboard_interrupt")):
        try:
            loop.add_signal_handler(sig, lambda reason=reason: request_stop(reason))
        except NotImplementedError:
            pass

    logger.info(
        "AUTO_RUNTIME_BOOT | execution_mode=%s live_trading_enabled=%s timezone=%s",
        APP_CONFIG.trading.execution_mode.value,
        APP_CONFIG.trading.live_trading_enabled,
        APP_CONFIG.session.market_timezone,
    )

    while not stop_event.is_set():
        decision = controller.evaluate()
        controller.log_decision(decision)

        if decision.action == RuntimeAction.RUN:
            logger.info(
                "AUTO_RUNTIME_SESSION_START | trading_day=%s session_close=%s",
                decision.trading_day.isoformat(),
                decision.session_close.isoformat(),
            )
            try:
                await runner()
            except Exception:
                logger.exception("AUTO_RUNTIME_SESSION_ERROR | trading_day=%s", decision.trading_day.isoformat())
                await _sleep_or_stop(stop_event, restart_delay_seconds)
            else:
                logger.info("AUTO_RUNTIME_SESSION_END | trading_day=%s", decision.trading_day.isoformat())
            continue

        now = calendar.as_market_datetime()
        sleep_seconds = compute_sleep_seconds(
            decision.next_check_at,
            now,
            max_sleep_seconds=idle_max_seconds,
        )
        logger.info(
            "AUTO_RUNTIME_WAIT | action=%s reason=%s phase=%s next_check_at=%s sleep_seconds=%.1f",
            decision.action.value,
            decision.reason,
            decision.phase,
            decision.next_check_at.isoformat(),
            sleep_seconds,
        )
        await _sleep_or_stop(stop_event, sleep_seconds)

    logger.info("AUTO_RUNTIME_EXIT")


async def main() -> None:
    configure_logging(log_file=APP_CONFIG.logging.file)
    await supervise_forever()


if __name__ == "__main__":
    asyncio.run(main())
