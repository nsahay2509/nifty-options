"""Run the live websocket in paper-evaluation mode during market hours."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.config import APP_CONFIG
from scripts.instrument_resolver import resolve_base_instruments
from scripts.log import configure_logging, get_logger
from scripts.market_calendar import MarketCalendar
from scripts.market_data import MarketDataService
from scripts.option_resolver import resolve_nifty_option_basket
from scripts.paper_mtm import PaperMtmTracker
from scripts.reporting import ReportingService
from scripts.run_research import evaluate_completed_candles
from scripts.runtime_controller import RuntimeController
from scripts.session_loader import load_prior_day_index_candles
from scripts.trade_recorder import TradeRecorder

if __package__ in {None, ""}:
    from scripts.brokers.credentials import load_dhan_credentials
    from scripts.brokers.dhan_market_feed import DhanMarketFeed
else:
    from .brokers.credentials import load_dhan_credentials
    from .brokers.dhan_market_feed import DhanMarketFeed


logger = get_logger("run_paper_live_eval")


async def main() -> None:
    configure_logging(log_file=APP_CONFIG.logging.file)

    if APP_CONFIG.trading.execution_mode.value != "paper" or APP_CONFIG.trading.live_trading_enabled:
        raise RuntimeError("run_paper_live_eval.py is paper-only and will not run in live order mode")

    calendar = MarketCalendar()
    controller = RuntimeController(calendar=calendar)
    decision = controller.evaluate()
    controller.log_decision(decision)
    if not decision.should_run:
        logger.info("PAPER_EVAL_SKIP | reason=%s next_check_at=%s", decision.reason, decision.next_check_at.isoformat())
        return

    credentials = load_dhan_credentials()
    resolved = resolve_base_instruments(as_of=decision.trading_day)
    prior_day_candles = load_prior_day_index_candles(decision.trading_day, calendar=calendar)
    option_anchor = prior_day_candles[-1].close if prior_day_candles else 23000.0
    try:
        option_instruments = resolve_nifty_option_basket(
            center_price=option_anchor,
            expiry_hint="same_week",
            as_of=decision.trading_day,
            breadth_steps=12,
        )
    except Exception as exc:
        logger.warning("PAPER_EVAL_OPTION_BASKET_SKIP | reason=%s", exc)
        option_instruments = []
    instruments = [resolved.index, resolved.futures, *option_instruments]

    logger.info(
        "PAPER_EVAL_START | trading_day=%s prior_day_candles=%s instruments=%s",
        decision.trading_day.isoformat(),
        len(prior_day_candles),
        ",".join(f"{inst.name}:{inst.security_id}" for inst in instruments),
    )

    market_data = MarketDataService()
    feed = DhanMarketFeed(credentials)
    recorder = TradeRecorder()
    reporter = ReportingService()
    mtm_tracker = PaperMtmTracker()
    stop_event = asyncio.Event()
    shutdown_reason = "session_end"

    def request_stop(reason: str) -> None:
        nonlocal shutdown_reason
        if stop_event.is_set():
            return
        shutdown_reason = reason
        logger.info("PAPER_EVAL_STOP_REQUESTED | reason=%s", reason)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig, reason in ((signal.SIGTERM, "manual_stop"), (signal.SIGINT, "keyboard_interrupt")):
        try:
            loop.add_signal_handler(sig, lambda reason=reason: request_stop(reason))
        except NotImplementedError:
            pass

    session_candles: list = []
    futures_candles: list = []
    tick_counter = 0
    decision_counter = 0
    max_ticks = int(os.getenv("PAPER_EVAL_MAX_TICKS", "0"))
    max_decisions = int(os.getenv("PAPER_EVAL_MAX_DECISIONS", "0"))
    session_file = None

    def record_result(candle, result) -> None:
        nonlocal decision_counter, session_file
        decision_counter += 1
        logger.info(
            "PAPER_EVAL_RESULT | state=%s playbook=%s structure=%s no_trade=%s",
            result.state_assessment.state_name,
            result.playbook_decision.playbook_name,
            result.structure_proposal.structure_type,
            result.playbook_decision.no_trade,
        )
        if result.playbook_decision.no_trade:
            mtm_tracker.close_active_position(reason="no_trade_signal")
            return

        trade_id = f"paper-{candle.start.strftime('%Y%m%d-%H%M')}-{decision_counter}"
        record = recorder.build_trade_record(
            trade_id=trade_id,
            state_at_entry=result.state_assessment.state_name,
            playbook=result.playbook_decision.playbook_name,
            structure=result.structure_proposal,
            gross_pnl=0.0,
            fees_and_costs=0.0,
        )
        session_file = recorder.append_trade_record(
            record,
            session_date=candle.start.strftime("%Y-%m-%d"),
            underlying_context={"underlying_price": candle.close, "paper_mode": True},
            expiry=result.structure_proposal.expiry,
            strikes=result.structure_proposal.strikes,
            side="PAPER",
            quantity=1,
            entry_price_or_prices=(result.structure_proposal.estimated_premium,),
            exit_price_or_prices=(),
            exit_reason="paper_eval_signal",
        )
        mtm_tracker.activate_position(
            trade_id=trade_id,
            session_date=candle.start.strftime("%Y-%m-%d"),
            playbook=result.playbook_decision.playbook_name,
            structure=result.structure_proposal,
            underlying_price=candle.close,
            quantity=1,
            as_of=decision.trading_day,
        )
        summary_path = reporter.write_summary(session_file)
        logger.info("PAPER_EVAL_RECORDED | trade_id=%s summary=%s", trade_id, summary_path)

    async def handle_tick(tick) -> bool:
        nonlocal tick_counter, shutdown_reason
        if stop_event.is_set():
            logger.info("PAPER_EVAL_STOP | reason=%s ticks=%s decisions=%s", shutdown_reason, tick_counter, decision_counter)
            return False

        tick_counter += 1
        mtm_tracker.on_tick(tick)
        completed = market_data.handle_tick(tick)
        for candle in completed:
            if candle.interval_min != 1:
                continue
            if candle.instrument.instrument_type == "INDEX":
                session_candles.append(candle)
                result = evaluate_completed_candles(
                    session_candles=session_candles,
                    futures_candles=futures_candles,
                    prior_day_candles=prior_day_candles,
                )
                if result is not None:
                    record_result(candle, result)
            elif candle.instrument.instrument_type == "FUTURES":
                futures_candles.append(candle)

        if max_ticks > 0 and tick_counter >= max_ticks:
            shutdown_reason = "max_ticks_reached"
            logger.info("PAPER_EVAL_STOP | reason=max_ticks_reached ticks=%s", tick_counter)
            return False
        if max_decisions > 0 and decision_counter >= max_decisions:
            shutdown_reason = "max_decisions_reached"
            logger.info("PAPER_EVAL_STOP | reason=max_decisions_reached decisions=%s", decision_counter)
            return False
        return True

    await controller.consume_stream(
        feed.stream(instruments),
        handle_tick,
        item_name="paper_eval_tick",
    )
    mtm_tracker.close_active_position(reason=shutdown_reason)


if __name__ == "__main__":
    asyncio.run(main())
