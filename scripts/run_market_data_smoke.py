"""Market-data smoke runner for Dhan websocket connectivity and candle generation."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.config import APP_CONFIG
from scripts.instrument_resolver import resolve_base_instruments
from scripts.log import configure_logging, get_logger
from scripts.market_calendar import MarketCalendar
from scripts.market_data import MarketDataService
from scripts.run_research import evaluate_completed_candles
from scripts.runtime_controller import RuntimeController

if __package__ in {None, ""}:
    from scripts.brokers.credentials import load_dhan_credentials
    from scripts.brokers.dhan_market_feed import DhanMarketFeed
else:
    from .brokers.credentials import load_dhan_credentials
    from .brokers.dhan_market_feed import DhanMarketFeed


logger = get_logger("run_market_data_smoke")


async def main() -> None:
    configure_logging(log_file=APP_CONFIG.logging.file)

    calendar = MarketCalendar()
    controller = RuntimeController(calendar=calendar)
    decision = controller.evaluate()
    controller.log_decision(decision)
    if not decision.should_run:
        logger.info(
            "SMOKE_SKIP | reason=%s next_check_at=%s",
            decision.reason,
            decision.next_check_at.isoformat(),
        )
        return

    day_context = calendar.describe_day(decision.trading_day)
    credentials = load_dhan_credentials()
    resolved = resolve_base_instruments(as_of=decision.trading_day)
    instruments = [resolved.index, resolved.futures]

    logger.info(
        "SMOKE_START | execution_mode=%s broker=%s trading_day=%s tags=%s instruments=%s",
        APP_CONFIG.trading.execution_mode.value,
        APP_CONFIG.broker.name.value,
        decision.trading_day.isoformat(),
        ",".join(day_context.tags),
        ",".join(f"{inst.name}:{inst.security_id}" for inst in instruments),
    )

    market_data = MarketDataService()
    feed = DhanMarketFeed(credentials)
    tick_counter = 0
    session_candles: list = []
    futures_candles: list = []

    async def handle_tick(tick) -> bool:
        nonlocal tick_counter

        tick_counter += 1
        completed = market_data.handle_tick(tick)
        logger.info(
            "TICK | instrument=%s sid=%s ltp=%s volume=%s oi=%s",
            tick.instrument.name,
            tick.instrument.security_id,
            tick.ltp,
            tick.volume,
            tick.open_interest,
        )
        for candle in completed:
            logger.info(
                "CANDLE | instrument=%s interval=%sm start=%s close=%s volume=%s ticks=%s",
                candle.instrument.name,
                candle.interval_min,
                candle.start.isoformat(),
                candle.close,
                candle.volume,
                candle.tick_count,
            )
            if candle.interval_min == 1:
                if candle.instrument.instrument_type == "INDEX":
                    session_candles.append(candle)
                elif candle.instrument.instrument_type == "FUTURES":
                    futures_candles.append(candle)
                result = evaluate_completed_candles(
                    session_candles=session_candles,
                    futures_candles=futures_candles,
                )
                if result is not None:
                    logger.info(
                        "PAPER_EVAL_RESULT | state=%s playbook=%s structure=%s no_trade=%s",
                        result.state_assessment.state_name,
                        result.playbook_decision.playbook_name,
                        result.structure_proposal.structure_type,
                        result.playbook_decision.no_trade,
                    )
        if tick_counter >= 20:
            logger.info("SMOKE_STOP | reason=max_ticks_reached ticks=%s", tick_counter)
            return False
        return True

    await controller.consume_stream(
        feed.stream(instruments),
        handle_tick,
        item_name="tick",
    )

    for builder in market_data.builders.values():
        for candle in builder.flush():
            market_data.candle_store.append(candle)
            logger.info(
                "CANDLE_FLUSH | instrument=%s interval=%sm start=%s close=%s volume=%s ticks=%s",
                candle.instrument.name,
                candle.interval_min,
                candle.start.isoformat(),
                candle.close,
                candle.volume,
                candle.tick_count,
            )


if __name__ == "__main__":
    asyncio.run(main())
