"""Run the live websocket in paper-evaluation mode during market hours."""

from __future__ import annotations

import asyncio
import csv
import json
import os
import signal
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.config import APP_CONFIG, DATA_DIR
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


@dataclass(frozen=True)
class TradeStateGateDecision:
    action: str
    active_state: str = ""
    candidate_state: str = ""
    candidate_count: int = 0
    opposite_count: int = 0
    reason: str = ""


class TradeStateGate:
    """Debounces rapid state flips before opening or closing paper trades."""

    def __init__(self, *, entry_confirmations_required: int = 3, exit_confirmations_required: int = 3) -> None:
        self.entry_confirmations_required = max(int(entry_confirmations_required), 1)
        self.exit_confirmations_required = max(int(exit_confirmations_required), 1)
        self._active_state = ""
        self._candidate_state = ""
        self._candidate_count = 0
        self._opposite_count = 0

    def observe(self, *, state_name: str, no_trade: bool) -> TradeStateGateDecision:
        observed_state = "NO_TRADE" if no_trade else str(state_name or "")

        if observed_state == self._candidate_state and observed_state:
            self._candidate_count += 1
        else:
            self._candidate_state = observed_state
            self._candidate_count = 1 if observed_state else 0

        if not self._active_state:
            if not observed_state or observed_state == "NO_TRADE":
                return TradeStateGateDecision(
                    action="wait",
                    active_state="",
                    candidate_state=self._candidate_state,
                    candidate_count=self._candidate_count,
                    reason="waiting_for_tradeable_state_confirmation",
                )
            if self._candidate_count >= self.entry_confirmations_required:
                self._active_state = observed_state
                self._opposite_count = 0
                return TradeStateGateDecision(
                    action="enter",
                    active_state=self._active_state,
                    candidate_state=self._candidate_state,
                    candidate_count=self._candidate_count,
                    reason="entry_state_confirmed",
                )
            return TradeStateGateDecision(
                action="wait",
                active_state="",
                candidate_state=self._candidate_state,
                candidate_count=self._candidate_count,
                reason="entry_confirmation_pending",
            )

        if observed_state == self._active_state:
            self._opposite_count = 0
            return TradeStateGateDecision(
                action="hold",
                active_state=self._active_state,
                candidate_state=self._candidate_state,
                candidate_count=self._candidate_count,
                opposite_count=self._opposite_count,
                reason="active_state_still_confirmed",
            )

        self._opposite_count += 1
        if self._opposite_count < self.exit_confirmations_required:
            return TradeStateGateDecision(
                action="hold",
                active_state=self._active_state,
                candidate_state=self._candidate_state,
                candidate_count=self._candidate_count,
                opposite_count=self._opposite_count,
                reason="exit_confirmation_pending",
            )

        previous_state = self._active_state
        self._active_state = ""
        self._opposite_count = 0

        if observed_state and observed_state != "NO_TRADE" and self._candidate_count >= self.entry_confirmations_required:
            self._active_state = observed_state
            return TradeStateGateDecision(
                action="switch",
                active_state=self._active_state,
                candidate_state=self._candidate_state,
                candidate_count=self._candidate_count,
                reason=f"confirmed_state_change:{previous_state}->{observed_state}",
            )

        return TradeStateGateDecision(
            action="exit",
            active_state="",
            candidate_state=self._candidate_state,
            candidate_count=self._candidate_count,
            reason=f"confirmed_exit_from:{previous_state}",
        )


def _expected_option_expiry_hint(as_of: date) -> str:
    calendar = MarketCalendar()
    try:
        days_to_expiry = max((calendar.next_expiry(as_of) - as_of).days, 0)
    except Exception:
        days_to_expiry = 0
    return "same_week" if days_to_expiry <= 3 else "next_week"


def _load_recent_underlying_price(*, session_date: date) -> float:
    live_mtm_file = DATA_DIR / "reports" / "live_paper_mtm.json"
    if live_mtm_file.exists():
        try:
            payload = json.loads(live_mtm_file.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if str(payload.get("session_date", "")) == session_date.isoformat():
            try:
                underlying = float(payload.get("underlying_price", 0.0) or 0.0)
            except (TypeError, ValueError):
                underlying = 0.0
            if underlying > 0:
                return underlying

    recent_record_files = [DATA_DIR / "records" / f"trade_records_{session_date.isoformat()}.csv"]
    records_dir = DATA_DIR / "records"
    if records_dir.exists():
        historical_files = sorted(records_dir.glob("trade_records_*.csv"), reverse=True)
        for candidate in historical_files:
            if candidate not in recent_record_files:
                recent_record_files.append(candidate)

    for records_file in recent_record_files:
        if not records_file.exists():
            continue
        try:
            with records_file.open(encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
        except Exception:
            rows = []
        for row in reversed(rows):
            try:
                context = json.loads(row.get("underlying_context", "") or "{}")
            except Exception:
                context = {}
            if not isinstance(context, dict):
                continue
            try:
                underlying = float(context.get("underlying_price", 0.0) or 0.0)
            except (TypeError, ValueError):
                underlying = 0.0
            if underlying > 0:
                return underlying

    return 0.0


def build_option_subscription_basket(
    *,
    center_price: float,
    as_of: date,
    prior_day_candles: list | None = None,
) -> list:
    """Subscribe to a focused option basket around the expected active expiry so live paper P&L can mark the current legs without overloading the feed."""
    if center_price <= 0:
        return []

    breadth_steps = 10
    expiry_hint = _expected_option_expiry_hint(as_of)
    fallback_hints = [expiry_hint]
    if expiry_hint != "same_week":
        fallback_hints.append("same_week")

    instruments = []
    seen: set[str] = set()

    for hint in fallback_hints:
        try:
            basket = resolve_nifty_option_basket(
                center_price=center_price,
                expiry_hint=hint,
                as_of=as_of,
                breadth_steps=breadth_steps,
            )
        except Exception as exc:
            logger.warning("PAPER_EVAL_OPTION_BASKET_SKIP | expiry_hint=%s reason=%s", hint, exc)
            continue

        for instrument in basket:
            if instrument.security_id in seen:
                continue
            seen.add(instrument.security_id)
            instruments.append(instrument)

        if instruments:
            logger.info(
                "PAPER_EVAL_OPTION_SUBSCRIPTIONS | center_price=%s expiry_hint=%s breadth_steps=%s option_count=%s",
                center_price,
                hint,
                breadth_steps,
                len(instruments),
            )
            break

    return instruments


async def main(*, stop_event: asyncio.Event | None = None, install_signal_handlers: bool = True) -> None:
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
    option_anchor = _load_recent_underlying_price(session_date=decision.trading_day)
    if option_anchor <= 0 and prior_day_candles:
        option_anchor = float(prior_day_candles[-1].close)
    if option_anchor <= 0:
        option_anchor = 23000.0
    option_instruments = build_option_subscription_basket(
        center_price=option_anchor,
        as_of=decision.trading_day,
        prior_day_candles=prior_day_candles,
    )
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
    trading_session_date = decision.trading_day.isoformat()

    def record_closed_trade(closed_trade: dict[str, object]) -> None:
        trade_id = str(closed_trade.get("trade_id", "") or "")
        if not trade_id:
            return

        legs = list(closed_trade.get("legs", [])) if isinstance(closed_trade.get("legs", []), list) else []
        exit_prices = tuple(
            float(leg.get("last_price", 0.0) or 0.0)
            for leg in legs
            if isinstance(leg, dict) and leg.get("last_price") is not None
        )
        target = recorder.finalize_trade_record(
            trade_id=trade_id,
            session_date=str(closed_trade.get("session_date", trading_session_date) or trading_session_date),
            gross_pnl=float(closed_trade.get("realised_pnl", 0.0) or 0.0),
            fees_and_costs=0.0,
            exit_price_or_prices=exit_prices,
            exit_reason=str(closed_trade.get("exit_reason", "") or ""),
            closed_at=str(closed_trade.get("closed_at", "") or ""),
            underlying_exit_price=float(closed_trade.get("underlying_price", 0.0) or 0.0),
            exit_close_value=float(closed_trade.get("current_close_value", 0.0) or 0.0),
            unrealised_pnl=0.0,
            legs=legs,
        )
        if target is None:
            return

        summary_path = reporter.write_summary(target)
        logger.info("PAPER_EVAL_CLOSE_RECORDED | trade_id=%s summary=%s", trade_id, summary_path)

    mtm_tracker = PaperMtmTracker(session_date=trading_session_date, on_trade_closed=record_closed_trade)
    state_gate = TradeStateGate(
        entry_confirmations_required=APP_CONFIG.trading.entry_confirmations_required,
        exit_confirmations_required=APP_CONFIG.trading.exit_confirmations_required,
    )
    stop_event = stop_event or asyncio.Event()
    shutdown_reason = "session_end"

    def request_stop(reason: str) -> None:
        nonlocal shutdown_reason
        if stop_event.is_set():
            return
        shutdown_reason = reason
        logger.info("PAPER_EVAL_STOP_REQUESTED | reason=%s", reason)
        stop_event.set()

    if install_signal_handlers:
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
        gate_decision = state_gate.observe(
            state_name=result.state_assessment.state_name,
            no_trade=result.playbook_decision.no_trade,
        )
        logger.info(
            "PAPER_EVAL_GATE | state=%s no_trade=%s action=%s active_state=%s candidate=%s candidate_count=%s opposite_count=%s reason=%s",
            result.state_assessment.state_name,
            result.playbook_decision.no_trade,
            gate_decision.action,
            gate_decision.active_state,
            gate_decision.candidate_state,
            gate_decision.candidate_count,
            gate_decision.opposite_count,
            gate_decision.reason,
        )

        if gate_decision.action == "wait":
            return

        if gate_decision.action == "hold":
            return

        if gate_decision.action in {"exit", "switch"}:
            mtm_tracker.close_active_position(reason=gate_decision.reason)
            if gate_decision.action == "exit" or result.playbook_decision.no_trade:
                return

        trade_id = f"paper-{candle.start.strftime('%Y%m%d-%H%M')}-{decision_counter}"
        snapshot = mtm_tracker.activate_position(
            trade_id=trade_id,
            session_date=candle.start.strftime("%Y-%m-%d"),
            playbook=result.playbook_decision.playbook_name,
            structure=result.structure_proposal,
            underlying_price=candle.close,
            quantity=1,
            as_of=decision.trading_day,
        )

        active_trade_id = str(snapshot.get("trade_id", "") or "")
        if active_trade_id != trade_id:
            logger.info(
                "PAPER_EVAL_POSITION_REUSED | requested_trade_id=%s active_trade_id=%s playbook=%s",
                trade_id,
                active_trade_id,
                result.playbook_decision.playbook_name,
            )
            return

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
            status="OPEN",
            opened_at=candle.end.isoformat(),
            entry_reason=result.playbook_decision.reason,
            entry_credit=float(snapshot.get("entry_credit", 0.0) or 0.0),
            entry_debit=float(snapshot.get("entry_debit", 0.0) or 0.0),
            exit_close_value=float(snapshot.get("current_close_value", 0.0) or 0.0),
            realised_pnl=0.0,
            unrealised_pnl=float(snapshot.get("unrealised_pnl", 0.0) or 0.0),
            legs=list(snapshot.get("legs", [])) if isinstance(snapshot.get("legs", []), list) else [],
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
    post_run_decision = controller.evaluate()
    if post_run_decision.should_run:
        mtm_tracker.preserve_active_position(reason="Active paper trade preserved for in-session restart.")
    else:
        mtm_tracker.close_active_position(reason=shutdown_reason)


if __name__ == "__main__":
    asyncio.run(main())
